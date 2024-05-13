from __future__ import annotations
from statistics import mean
from typing import Optional

import numpy as np
from qat.clinalg.qpu import CLinalg
from qat.comm.qlmaas.ttypes import JobStatus as QLM_JobStatus, QLMServiceException
from qat.core.contexts import QPUContext
from qat.core.qpu.qpu import QPUHandler
from qat.core.wrappers.circuit import Circuit
from qat.core.wrappers.job import Job as JobQLM
from qat.core.wrappers.observable import Observable as QLM_Observable
from qat.core.wrappers.result import Result as QLM_Result
from qat.plugins.observable_splitter import ObservableSplitter
from qat.pylinalg import PyLinalg
from qat.qlmaas.result import AsyncResult
from qat.hardware.default import HardwareModel, DefaultGatesSpecification
from qat.quops.quantum_channels import ParametricGateNoise

from typeguard import typechecked

from mpqp import Language, QCircuit
from mpqp.core.instruction.measurement import ComputationalBasis
from mpqp.core.instruction.measurement.basis_measure import BasisMeasure
from mpqp.core.instruction.measurement.expectation_value import (
    ExpectationMeasure,
    Observable,
)
from mpqp.execution.devices import ATOSDevice
from mpqp.noise.noise_model import NoiseModel, Depolarizing
from ...core.instruction.gates.native_gates import NoParameterGate, RotationGate, U

from ...tools.errors import QLMRemoteExecutionError, DeviceJobIncompatibleError
from ..connection.qlm_connection import get_QLMaaSConnection
from ..job import Job, JobStatus, JobType
from ..result import Result, Sample, StateVector


@typechecked
def job_pre_processing(job: Job) -> Circuit:
    """Extracts the myQLM circuit and check if ``job.type`` and ``job.measure``
    are coherent.

    Args:
        job: Mpqp job used to instantiate the myQLM circuit.

    Returns:
          The myQLM Circuit translated from the circuit of the job in parameter.
    """

    if (
        job.job_type == JobType.STATE_VECTOR
        and job.measure is not None
        and not isinstance(job.measure, BasisMeasure)
    ):
        raise ValueError("`STATE_VECTOR` jobs require `BasisMeasure` to be run.")
    if job.job_type == JobType.OBSERVABLE and not isinstance(
        job.measure, ExpectationMeasure
    ):
        raise ValueError("`OBSERVABLE` jobs require `ExpectationMeasure` to be run.")
    if job.job_type == JobType.STATE_VECTOR and job.device.is_noisy_simulator():
        raise DeviceJobIncompatibleError("Noisy simulators cannot be used for `STATE_VECTOR` jobs.")

    myqlm_circuit = job.circuit.to_other_language(Language.MY_QLM)

    return myqlm_circuit


@typechecked
def get_local_qpu(device: ATOSDevice) -> QPUHandler:
    """Returns the myQLM local QPU associated with the ATOSDevice given in
    parameter.

    Args:
        device: ATOSDevice referring to the myQLM local QPU.

    Raises:
        ValueError: If the required backend is a local simulator.
    """
    if device.is_remote():
        raise ValueError(f"Excepted a local device, not the remote QLM device {device}")
    if device == ATOSDevice.MYQLM_PYLINALG:
        return PyLinalg()
    return CLinalg()


@typechecked
def get_remote_qpu(device: ATOSDevice, job: Job = None):

    if not device.is_remote():
        raise ValueError(f"Excepted a remote device, but got a local myQLM simulator {device}")
    if job is not None and job.circuit.noises:
        if not device.is_noisy_simulator():
            raise DeviceJobIncompatibleError(f"Excepted a noisy remote simulator but got {device}")

        if device == ATOSDevice.QLM_NOISYQPROC:
            get_QLMaaSConnection()
            from qlmaas.qpus import NoisyQProc  # type: ignore
            hw_model = generate_hardware_model(job.circuit.noises, job.circuit.nb_qubits)
            return NoisyQProc(hw_model, n_samples=job.measure.shots)
        elif device == ATOSDevice.QLM_MPO:
            get_QLMaaSConnection()
            from qlmaas.qpus import MPO  # type: ignore
            hw_model = generate_hardware_model(job.circuit.noises, job.circuit.nb_qubits)
            return MPO(hw_model)
        else:
            raise DeviceJobIncompatibleError(f"Device {device.name} not handled for noisy simulations. ")
    else:
        if device == ATOSDevice.QLM_LINALG:
            get_QLMaaSConnection()
            from qlmaas.qpus import LinAlg  # type: ignore
            return LinAlg()
        elif device == ATOSDevice.QLM_MPS:
            get_QLMaaSConnection()
            from qlmaas.qpus import MPS  # type: ignore
            return MPS()
        elif device == ATOSDevice.QLM_NOISYQPROC:
            get_QLMaaSConnection()
            from qlmaas.qpus import NoisyQProc  # type: ignore
            return NoisyQProc(n_samples=0 if job.measure is None else job.measure.shots)
        elif device == ATOSDevice.QLM_MPO:
            get_QLMaaSConnection()
            from qlmaas.qpus import MPO  # type: ignore
            return MPO()
        else:
            raise DeviceJobIncompatibleError(f"Device {device.name} not handled for noiseless simulations.")


@typechecked
def generate_state_vector_job(
    myqlm_circuit: Circuit
) -> JobQLM:
    """Generates a myQLM job from the myQLM circuit.

    Args:
        myqlm_circuit: MyQLM circuit of the job.

    Returns:
        A myQLM Job to retrieve the statevector of the circuit.
    """

    return myqlm_circuit.to_job(job_type="SAMPLE")


@typechecked
def generate_sample_job(myqlm_circuit: Circuit, job: Job) -> JobQLM:
    """Generates a myQLM job from the myQLM circuit and job sample info (target, shots, ...).

    Args:
        myqlm_circuit: MyQLM circuit of the job.
        job: Original mpqp job used to generate the myQLM job.

    Returns:
        A myQLM Job for sampling the circuit according to the mpqp Job parameters.
    """

    assert job.measure is not None

    myqlm_job = myqlm_circuit.to_job(
        job_type="SAMPLE",
        qubits=job.measure.targets,
        nbshots=job.measure.shots,
    )

    return myqlm_job


@typechecked
def generate_observable_job(
    myqlm_circuit: Circuit, job: Job
) -> JobQLM:
    """Generates a myQLM job from the myQLM circuit and observable.

    Args:
        myqlm_circuit: MyQLM circuit of the job.
        job: Original mpqp job used to generate the myQLM job.

    Returns:
        A myQLM Job for retrieving the expectation value of the observable.
    """

    assert job.measure is not None and isinstance(job.measure, ExpectationMeasure)

    myqlm_job = myqlm_circuit.to_job(
        job_type="OBS",
        observable=QLM_Observable(
            job.measure.nb_qubits, matrix=job.measure.observable.matrix
        ),
        nbshots=job.measure.shots,
    )

    return myqlm_job


@typechecked
def generate_hardware_model(noises: list[NoiseModel], nb_qubits: int) -> HardwareModel:
    """

    Args:
        noises: List of NoiseModel of a QCircuit used to generate a QLM HardwareModel.
        nb_qubits: Number of qubits of the circuit.

    Returns:

    """
    #TODO: comment and implement
    all_qubits_target = True

    gate_noise_global = dict() # {"H": QuantumChannel, ...}
    gate_noise_dicts = dict() # {"H": {0: QuantumChannel, 1: QuantumChannel}}
    idle_global_list = [] # [ Quantum Channel, ...]
    idle_dicts = dict() # {0: ..., 1: ...}
    nb_param_keyword = {'PH': 1, 'CNOT': 0}

    # For each noise model
    for noise in noises:
        this_noise_all_qubits_target = True

        channel = noise.to_other_language(Language.MY_QLM)

        if noise.targets != list(range(nb_qubits)):
            this_noise_all_qubits_target = False
            all_qubits_target = False

        if noise.gates:
            # For each gate attached to this NoiseModel, we add to each gate key the right channels
            for gate in noise.gates:
                if hasattr(gate, "qlm_aqasm_keyword"):
                    gate_keywords = gate.qlm_aqasm_keyword
                    was_list = True
                    if not isinstance(gate_keywords, list):
                        gate_keywords = [gate_keywords]
                        was_list = False

                    # For each keyword corresponding to the gate
                    for keyword in gate_keywords:
                        # Determine the number of parameters of the gate
                        if not was_list:
                            if issubclass(gate, NoParameterGate):
                                nb_param_keyword[keyword] = 0
                            elif issubclass(gate, RotationGate):
                                nb_param_keyword[keyword] = 1
                            elif gate == U:
                                nb_param_keyword[keyword] = 3
                            else:
                                raise ValueError(f"Unknown native gate {gate}. Must be either a NoParameterGate, a "
                                                 f"RotationGate or the U gate.")

                        # If the target are all qubits
                        if this_noise_all_qubits_target:
                            if keyword not in gate_noise_global:
                                gate_noise_global[keyword] = channel
                            else:
                                gate_noise_global[keyword] *= channel

                        else:
                            if keyword not in gate_noise_dicts:
                                gate_noise_dicts[keyword] = dict()

                            for target in noise.targets:
                                if target not in gate_noise_dicts[keyword]:
                                    gate_noise_dicts[keyword][target] = channel
                                else:
                                    gate_noise_dicts[keyword][target] *= channel

        # Otherwise, we add an iddle noise
        else:
            if this_noise_all_qubits_target:
                idle_global_list.append(channel)
            else:
                for target in noise.targets:
                    if target not in idle_dicts:
                        idle_dicts[target] = []
                    idle_dicts[target].append(channel)

    print(gate_noise_global)
    print(gate_noise_dicts)
    print(idle_global_list)
    print(idle_dicts)
    print(nb_param_keyword)

    # Only use the lists
    if all_qubits_target:

        dict_gate_noise_lambdas = dict()

        for keyword in gate_noise_global.keys():
            # We create a lambda function with as much anonymous parameters as the number of parameters of the gate
            # related with the keyword, and return the right QuantumChannel
            dict_gate_noise_lambdas[keyword] = eval(
                "lambda " + ", ".join(["_"+str(i) for i in range(nb_param_keyword[keyword])]) +
                ": gate_noise_global[keyword]"
            )

        return HardwareModel(DefaultGatesSpecification(),
                             gate_noise=dict_gate_noise_lambdas,
                             idle_noise=idle_global_list)

    # Incorporate the lists into the dict for all qubits
    else:

        # We have lists, that concern all qubits, and we have dictionnaries that concern only some qubits
        # For gates, we take the gate_noise_global and for each keyword in it,
            # If the keyword already exists in the other dict, for each qubit
                # If the qubit is already existing --> we compose the channels
                # Otherwise we add the channel to the corresponding qubit
            # If it doesnt exist, we only add the quantum channel to the key, so for all qubits

        for keyword in gate_noise_global.keys():
            if keyword in gate_noise_dicts:
                for qubit in range(nb_qubits):
                    if qubit in gate_noise_dicts[keyword]:
                        gate_noise_dicts[keyword][qubit] *= gate_noise_global[keyword]
                    else:
                        gate_noise_dicts[keyword][qubit] = gate_noise_global[keyword]
            else:
                gate_noise_dicts[keyword] = gate_noise_global[keyword]

        # Then we generate the lambda functions
        dict_gate_noise_lambdas = dict()
        for keyword in gate_noise_dicts.keys():
            if isinstance(gate_noise_dicts[keyword], dict):
                dict_gate_noise_lambdas[keyword] = dict()
                for qubit in gate_noise_dicts[keyword].keys():
                    dict_gate_noise_lambdas[keyword][qubit] = eval(
                        "(lambda " + ", ".join(["_" + str(i) for i in range(nb_param_keyword[keyword])]) +
                        ": gate_noise_dicts[keyword][qubit])"
                    )
            else:
                dict_gate_noise_lambdas[keyword] = eval(
                    "lambda " + ", ".join(["_" + str(i) for i in range(nb_param_keyword[keyword])]) +
                    ": gate_noise_dicts[keyword]"
                )

        # For iddle, we take the list of idle_global_lists and we add them to the list for each qubit in the dictionnary
        # and we only put the dictionnary
        for qubit in range(nb_qubits):
            if qubit in idle_dicts:
                idle_dicts[qubit].extend(idle_global_list)
            else:
                idle_dicts[qubit] = idle_global_list

        return HardwareModel(DefaultGatesSpecification(),
                             gate_noise=dict_gate_noise_lambdas,
                             idle_noise=idle_dicts)


@typechecked
def extract_state_vector_result(
    myqlm_result: QLM_Result,
    job: Optional[Job] = None,
    device: ATOSDevice = ATOSDevice.MYQLM_PYLINALG,
) -> Result:
    """Constructs a Result from the result given by the myQLM/QLM run in state
    vector mode.

    Args:
        myqlm_result: Result returned by myQLM/QLM after running of the job.
        job: Original mpqp job used to generate the run. Used to retrieve more
            easily info to instantiate the result.
        device: ATOSDevice on which the job was submitted. Used to know if the
            run was remote or local.

    Returns:
        A Result containing the result info extracted from the myQLM/QLM
        statevector result.
    """
    if job is None:
        nb_qubits = (
            myqlm_result.qregs[0].length
            if device.is_remote()
            else sum(len(qreg.qbits) for qreg in myqlm_result.data.qregs)
        )
        job = Job(JobType.STATE_VECTOR, QCircuit(nb_qubits), device, None)
    else:
        nb_qubits = job.circuit.nb_qubits

    nb_states = 2**nb_qubits
    amplitudes = np.zeros(nb_states, np.complex64)
    probas = np.zeros(nb_states, np.float32)
    for sample in myqlm_result:
        amplitudes[sample._state] = sample.amplitude
        probas[sample._state] = sample.probability

    return Result(job, StateVector(amplitudes, nb_qubits, probas), 0, 0)


@typechecked
def extract_sample_result(
    myqlm_result: QLM_Result,
    job: Optional[Job] = None,
    device: ATOSDevice = ATOSDevice.MYQLM_PYLINALG,
) -> Result:
    """Constructs a Result from the result given by the myQLM/QLM run in sample
    mode.

    Args:
        myqlm_result: Result returned by myQLM/QLM after running of the job.
        job: Original mpqp job used to generate the run. Used to retrieve more
            easily info to instantiate the result.
        device: ATOSDevice on which the job was submitted. Used to know if the
            run was remote or local.

    Returns:
        A Result containing the result info extracted from the myQLM/QLM sample
        result.
    """
    # TODO: check what to modify in the noisy case
    if job is None:
        assert isinstance(myqlm_result.qregs[0].length, int)
        nb_qubits = (
            myqlm_result.qregs[0].length
            if device.is_remote()
            else sum(len(qreg.qbits) for qreg in myqlm_result.raw_data.qregs)
        )
        nb_shots = int(myqlm_result.meta_data["nbshots"])
        job = Job(
            JobType.SAMPLE,
            QCircuit(nb_qubits),
            device,
            BasisMeasure(targets=list(range(nb_qubits)), shots=nb_shots),
        )
    else:
        nb_qubits = job.circuit.nb_qubits
        if job.measure is None:
            raise NotImplementedError("We cannot handle job without measure for now")
        nb_shots = job.measure.shots

    # we here take the average of errors over all samples
    error = mean([sample.err for sample in myqlm_result])
    samples = [
        Sample(
            nb_qubits,
            index=sample._state,
            probability=sample.probability,
            bin_str=str(sample.state)[1:-1],
        )
        for sample in myqlm_result
    ]

    return Result(job, samples, error, nb_shots)


@typechecked
def extract_observable_result(
    myqlm_result: QLM_Result,
    job: Optional[Job] = None,
    device: ATOSDevice = ATOSDevice.MYQLM_PYLINALG,
) -> Result:
    """Constructs a Result from the result given by the myQLM/QLM run in
    observable mode.

    Args:
        myqlm_result: Result returned by myQLM/QLM after running of the job.
        job: Original mpqp job used to generate the run. Used to retrieve more
            easily info to instantiate the result.
        device: ATOSDevice on which the job was submitted. Used to know if the
            run was remote or local.

    Returns:
        A Result containing the result info extracted from the myQLM/QLM
        observable result.
    """
    # TODO: check what to modify in the noisy case
    if job is None:
        if device.is_remote():
            nb_qubits = myqlm_result.data.qregs[0].length
        else:
            nb_qubits = sum(len(qreg.qbits) for qreg in myqlm_result.data.qregs)
        nb_shots = int(myqlm_result.meta_data["nbshots"])
        job = Job(
            JobType.OBSERVABLE,
            QCircuit(nb_qubits),
            device,
            ExpectationMeasure(
                targets=list(range(nb_qubits)),
                observable=Observable(
                    np.zeros((2**nb_qubits, 2**nb_qubits), dtype=np.complex64)
                ),
                shots=nb_shots,
            ),
        )
    else:
        if job.measure is None:
            raise NotImplementedError("We cannot handle job without measure for now")
        nb_shots = job.measure.shots

    return Result(job, myqlm_result.value, myqlm_result.error, nb_shots)


@typechecked
def extract_result(
    myqlm_result: QLM_Result,
    job: Optional[Job] = None,
    device: ATOSDevice = ATOSDevice.MYQLM_PYLINALG,
) -> Result:
    """Constructs a Result from the result given by the myQLM/QLM run.

    Args:
        myqlm_result: Result returned by myQLM/QLM after running of the job.
        job: Original mpqp job used to generate the run. Used to retrieve more
            easily info to instantiate the result.
        device: ATOSDevice on which the job was submitted. Used to know if the
            run was remote or local.

    Returns:
        A Result containing the result info extracted from the myQLM/QLM result.
    """
    # TODO: check what to modify in the noisy case
    if (job is None) or job.device.is_remote():
        if myqlm_result.value is None:
            if list(myqlm_result)[0].amplitude is None:
                job_type = JobType.SAMPLE
            else:
                job_type = JobType.STATE_VECTOR
        else:
            job_type = JobType.OBSERVABLE
    else:
        job_type = job.job_type

    if job_type == JobType.STATE_VECTOR:
        return extract_state_vector_result(myqlm_result, job, device)
    elif job_type == JobType.SAMPLE:
        return extract_sample_result(myqlm_result, job, device)
    else:
        return extract_observable_result(myqlm_result, job, device)


@typechecked
def run_atos(job: Job) -> Result:
    """Executes the job on the right ATOS device precised in the job in
    parameter.

    Note:
        This function is not meant to be used directly, please use
        ``runner.run(...)`` instead.

    Args:
        job: Job to be executed.

    Returns:
        A Result after submission and execution of the job.
    """
    return run_myQLM(job) if not job.device.is_remote() else run_QLM(job)


@typechecked
def run_myQLM(job: Job) -> Result:
    """Executes the job on the local myQLM simulator.

    Note:
        This function is not meant to be used directly, please use
        ``runner.run(...)`` instead.

    Args:
        job: Job to be executed.

    Returns:
        A Result after submission and execution of the job.
    """

    result = None
    myqlm_job = None
    myqlm_result = None
    qpu = None

    myqlm_circuit = job_pre_processing(job)

    assert isinstance(job.device, ATOSDevice)
    qpu = get_local_qpu(job.device)

    if job.job_type == JobType.STATE_VECTOR:
        myqlm_job = generate_state_vector_job(myqlm_circuit)

    elif job.job_type == JobType.SAMPLE:
        assert isinstance(job.measure, BasisMeasure)
        if isinstance(job.measure.basis, ComputationalBasis):
            myqlm_job = generate_sample_job(myqlm_circuit, job)
        else:
            raise NotImplementedError(
                "Does not handle other basis than the ComputationalBasis for the moment"
            )

    elif job.job_type == JobType.OBSERVABLE:
        assert isinstance(job.measure, ExpectationMeasure)
        myqlm_job = generate_observable_job(myqlm_circuit, job)

    else:
        raise ValueError(f"Job type {job.job_type} not handled")

    job.status = JobStatus.RUNNING
    myqlm_result = qpu.submit(myqlm_job)

    # retrieving the results
    result = extract_result(myqlm_result, job, job.device)  # type: ignore

    job.status = JobStatus.DONE
    return result


@typechecked
def submit_QLM(job: Job) -> tuple[str, AsyncResult]:
    """Submits the job on the remote QLM machine.

    Note:
        This function is not meant to be used directly, please use
        ``runner.submit(...)`` instead.

    Args:
        job: Job to be executed.

    Returns:
        The job_id and the AsyncResult of the submitted job.

    Raises:
        ValueError: TODO fill
    """

    myqlm_job = None
    qpu = None

    myqlm_circuit = job_pre_processing(job)

    assert isinstance(job.device, ATOSDevice)
    qpu = get_remote_qpu(job.device, job)

    if job.job_type == JobType.STATE_VECTOR:
        assert isinstance(job.device, ATOSDevice)
        myqlm_job = generate_state_vector_job(myqlm_circuit)

    elif job.job_type == JobType.SAMPLE:
        assert isinstance(job.measure, BasisMeasure)
        if isinstance(job.measure.basis, ComputationalBasis):
            myqlm_job = generate_sample_job(myqlm_circuit, job)
        else:
            raise NotImplementedError(
                "Does not handle other basis than the ComputationalBasis for the moment"
            )

    elif job.job_type == JobType.OBSERVABLE:
        assert isinstance(job.measure, ExpectationMeasure)
        myqlm_job = generate_observable_job(myqlm_circuit, job)

    else:
        raise ValueError(f"Job type {job.job_type} not handled")

    job.status = JobStatus.RUNNING
    async_result = qpu.submit(myqlm_job)
    job_id = async_result.get_info().id
    job.id = job_id

    return job_id, async_result


@typechecked
def run_QLM(job: Job) -> Result:
    """Submits the job on the remote QLM machine and waits for it to be done. This
    function is not meant to be used directly, please use ``runner.run(...)``
    instead.

    Args:
        job: Job to be executed.

    Returns:
        A Result after submission and execution of the job.

    Raises:
        ValueError: TODO fill
    """

    if not isinstance(job.device, ATOSDevice) or not job.device.is_remote():
        raise ValueError(
            "This job's device is not a QLM one, so it cannot be handled by this "
            "function. Use ``run`` instead."
        )

    _, async_result = submit_QLM(job)
    qlm_result = async_result.join()

    return extract_result(qlm_result, job, job.device)


@typechecked
def get_result_from_qlm_job_id(job_id: str) -> Result:
    """Retrieve the result, described by the job_id in parameter, from the
    remote QLM and convert it into an mpqp result. If the job is still running,
    we wait (blocking) until it is DONE.

    Args:
        job_id: Id of the remote QLM job.

    Raises:
        QLMRemoteExecutionError: TODO fill

    """
    connection = get_QLMaaSConnection()

    try:
        qlm_job = connection.get_job(job_id)
    except QLMServiceException:
        raise QLMRemoteExecutionError(f"Job with id {job_id} not found.") from None

    status = qlm_job.get_status()
    if status in [
        QLM_JobStatus.CANCELLED,
        QLM_JobStatus.UNKNOWN_JOB,
        QLM_JobStatus.DELETED,
        QLM_JobStatus.FAILED,
        QLM_JobStatus.STOPPED,
    ]:
        raise QLMRemoteExecutionError(
            f"Trying to retrieve a QLM result for a job in status {status.name}"
        )
    elif status in [QLM_JobStatus.WAITING, QLM_JobStatus.RUNNING]:
        qlm_job.join()

    qlm_result: QLM_Result = qlm_job.get_result()

    qlm_qpu_name = qlm_job.get_info().resources.qpu.split(':')[1]

    return extract_result(qlm_result, None, ATOSDevice.from_str_remote(qlm_qpu_name))
