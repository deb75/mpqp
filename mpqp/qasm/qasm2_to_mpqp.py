from __future__ import annotations
from venv import logger


import numpy as np  # pyright: ignore[reportUnusedImport]
from mpqp import QCircuit, Barrier
from mpqp.gates import *
from mpqp.measures import *

from ply.lex import lex

from mpqp.qasm.lexer_utils import *
from mpqp.qasm.open_qasm_2_and_3 import remove_user_gates, remove_include


# TODO:
# commentary "\\": not handle
# if: not handle
# barrier: handle for all qubits ("q"), not for multiple qubits ("q[0],q[1]")


def lex_openqasm(input_string: str) -> list[LexToken]:
    lexer = lex()
    lexer.input(input_string)
    tokens = []
    tok = lexer.token()
    while tok:
        tokens.append(tok)
        tok = lexer.token()
    return tokens


def qasm2_parse(input_string: str) -> QCircuit:
    input_string = remove_include(input_string)
    input_string = remove_user_gates(input_string)
    tokens = lex_openqasm(input_string)

    if (
        tokens[0].type != 'OPENQASM'
        and tokens[1].type != 'REALN'
        and tokens[1].value != '2.0'
        and tokens[2].type != 'SEMICOLON'
    ):
        raise SyntaxError('Invalid OpenQASM, must start with OPENQASM 2.0;')

    idx = 3
    if idx < len(tokens) and tokens[idx].type == 'QREG':
        if check_Id(tokens, idx + 1) and tokens[idx + 5].type != 'SEMICOLON':
            raise SyntaxError(
                'must  have a qreg with the number of qubit such as "qreg ID[INTN];": '
                + f'{" ".join(str(token.value) for token in tokens[idx : idx + 5])}'
            )
        circuit = QCircuit(tokens[idx + 3].value)
        idx += 6
    else:
        circuit = QCircuit(0)
    i_max = len(tokens)
    while idx < i_max:
        logger.debug(circuit)
        logger.debug('================================')
        logger.debug('new line:', tokens[idx].value, idx)
        idx = TokenSwitch(circuit, tokens, idx)

    return circuit


def TokenSwitch(circuit: QCircuit, tokens: list[LexToken], idx: int) -> int:
    token = tokens[idx]
    if token.type == 'CREG':
        return TokenCREG(circuit, tokens, idx)
    elif token.type == 'MEASURE':
        return TokenMeasure(circuit, tokens, idx)
    elif token.type == 'BARRIER':
        return TokenBarrier(circuit, tokens, idx)
    elif token.type == 'ID':
        return TokenGate(circuit, tokens, idx)
    else:
        raise SyntaxError(f"Invalid token: {idx} {token.type}")


def TokenCREG(circuit: QCircuit, tokens: list[LexToken], idx: int) -> int:
    idx += 1
    if check_Id(tokens, idx) or tokens[idx + 4].type != 'SEMICOLON':
        raise SyntaxError(' '.join(str(token.value) for token in tokens[idx : idx + 4]))
    circuit.nb_cbits = tokens[idx + 2].value
    return idx + 5


def TokenMeasure(circuit: QCircuit, tokens: list[LexToken], idx: int) -> int:
    targets = []
    idx += 1
    while tokens[idx].type != 'SEMICOLON' and tokens[idx].type != 'ARROW':
        if tokens[idx].type == 'ID' and tokens[idx + 1].type == 'ARROW':
            targets = None
            idx += 1
            break
        if check_Id(tokens, idx):
            raise SyntaxError(
                ' '.join(str(token.value) for token in tokens[idx : idx + 4])
            )
        targets.append(tokens[idx + 2].value)
        idx += 4
        if tokens[idx].type == 'COMMA':
            idx += 1

    c_targets = None
    if tokens[idx].type == 'ARROW':
        c_targets = []
        idx += 1
        while tokens[idx].type != 'SEMICOLON':
            if tokens[idx].type == 'ID' and tokens[idx + 1].type == 'SEMICOLON':
                c_targets = None
                idx += 1
                break
            if check_Id(tokens, idx):
                raise SyntaxError(
                    ' '.join(str(token.value) for token in tokens[idx : idx + 4])
                )
            c_targets.append(tokens[idx + 2].value)
            idx += 4
            if tokens[idx].type == 'COMMA':
                idx += 1

    circuit.add(BasisMeasure(targets, c_targets))
    return idx + 1


def TokenBarrier(circuit: QCircuit, tokens: list[LexToken], idx: int) -> int:
    idx += 2
    if tokens[idx].type != 'SEMICOLON':
        raise SyntaxError(f"Barrier: {idx} {tokens[idx]}")
    circuit.add(Barrier())
    return idx + 1


def TokenGate(circuit: QCircuit, tokens: list[LexToken], idx: int) -> int:
    token = tokens[idx]
    idx += 1

    if token.value in single_qubits_gate_qasm:
        return Gate_single_qubits(circuit, token.value, tokens, idx)
    elif token.value in two_qubits_gate_qasm:
        return Gate_two_qubits(circuit, token.value, tokens, idx)
    elif token.value in one_parametrized_gate_qasm:
        return Gate_one_parametrized(circuit, token.value, tokens, idx)
    elif token.value in u_gate_qasm:
        return Gate_U(circuit, token.value, tokens, idx)
    else:
        raise SyntaxError(f"TokenGate: {idx} {token.value}")


def Gate_single_qubits(
    circuit: QCircuit, gate_str: str, tokens: list[LexToken], idx: int
) -> int:
    if tokens[idx].type == 'ID' and tokens[idx + 1].type == 'SEMICOLON':
        for i in range(circuit.nb_qubits):
            circuit.add(single_qubits_gate_qasm[gate_str](i))
        return idx + 2
    while tokens[idx].type != 'SEMICOLON':
        if check_Id(tokens, idx):
            raise SyntaxError(
                f'Gate_single_qubits: {" ".join(str(token.value) for token in tokens[idx : idx + 4])}'
            )
        circuit.add(single_qubits_gate_qasm[gate_str](tokens[idx + 2].value))
        idx += 4
    return idx + 1


def Gate_two_qubits(
    circuit: QCircuit, gate_str: str, tokens: list[LexToken], idx: int
) -> int:
    if (
        check_Id(tokens, idx)
        or tokens[idx + 4].type != 'COMMA'
        or check_Id(tokens, idx + 5)
    ):
        raise SyntaxError(
            f'Gate_two_qubits: {" ".join(str(token.value) for token in tokens[idx : idx + 10])}'
        )

    control = tokens[idx + 2].value
    target = tokens[idx + 7].value
    circuit.add(two_qubits_gate_qasm[gate_str](control, target))
    return idx + 10


def eval_expr(tokens: list[LexToken], idx: int) -> tuple[Any, int]:
    expr = ""
    while tokens[idx].type != 'COMMA' and tokens[idx].type != 'RPAREN':
        if check_num_expr(tokens[idx].type):
            raise SyntaxError(f"not a nb or expr: {idx}, {tokens[idx]}")
        if tokens[idx].type == 'PI':
            expr += "np.pi"
        else:
            expr += str(tokens[idx].value)
        idx += 1
    return eval(expr), idx + 1


def Gate_one_parametrized(
    circuit: QCircuit, gate_str: str, tokens: list[LexToken], idx: int
) -> int:
    if tokens[idx].type != 'LPAREN':
        raise SyntaxError(f"Gate_one_parametrized: {idx} {tokens[idx]}")
    idx += 1
    parameter, idx = eval_expr(tokens, idx)
    if check_Id(tokens, idx):
        raise SyntaxError(
            f'Gate_two_qubits: {" ".join(token.value for token in tokens[idx : idx + 3])}'
        )
    target = tokens[idx + 2].value
    circuit.add(one_parametrized_gate_qasm[gate_str](parameter, target))
    return idx + 5


def Gate_U(circuit: QCircuit, gate_str: str, tokens: list[LexToken], idx: int) -> int:
    if tokens[idx].type != 'LPAREN':
        raise SyntaxError(f"Gate_U: {idx} {tokens[idx]}")
    idx += 1

    theta, phi, lbda = 0, 0, 0
    if gate_str == 'u1':
        theta, idx = eval_expr(tokens, idx)
    elif gate_str == 'u2':
        theta, idx = eval_expr(tokens, idx)
        phi, idx = eval_expr(tokens, idx)
    elif gate_str == 'u3' or gate_str == 'u':
        theta, idx = eval_expr(tokens, idx)
        phi, idx = eval_expr(tokens, idx)
        lbda, idx = eval_expr(tokens, idx)

    if check_Id(tokens, idx):
        raise SyntaxError(
            f'GateU:  {" ".join(str(token.value) for token in tokens[idx : idx + 4])}'
        )
    target = tokens[idx + 2].value
    circuit.add(U(theta, phi, lbda, target))
    return idx + 5
