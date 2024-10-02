""":class:`~mpqp.core.instruction.measurement.measure.Measure` is the
base class for measurements. It regroups all the attributes and methods
common to all types of measurements we support.

A measurement can be of two types:
:class:`~mpqp.core.instruction.measurement.basis_measure.BasisMeasure`
or
:class:`~mpqp.core.instruction.measurement.expectation_value.ExpectationMeasure`,
described in details bellow."""

from __future__ import annotations

from abc import ABC
from typing import Optional

from typeguard import TypeCheckError, typechecked

from mpqp.core.instruction import Instruction


@typechecked
class Measure(Instruction, ABC):
    """Abstract class representing the measurement of the quantum state
    generated by a quantum circuit.

    This class is used to regroup attributes and methods shared by all different
    types of measures.

    We distinguish two types of measures:

    - Basis measurement (measure some qubits in a specific basis, sample
      mode, or retrieve the StateVector when shots is equal to zero)
    - Expectation value (use of an observable, exact or sample mode)

    Args:
        targets: List of indices referring to the qubits on which the measure
            will be applied.
        shots: Number of times the circuit should be run, each of these times is
            called a shot.
        label: Label used to identify the measure.
    """

    def __init__(
        self,
        targets: list[int],
        shots: int = 0,
        label: Optional[str] = None,
    ):
        if shots < 0:
            raise TypeCheckError(
                f"Negative number of shot makes no sense, given {shots}"
            )
        super().__init__(targets, label)
        self.shots = shots
        """See parameter description."""
        self.label = label
        """See parameter description."""
