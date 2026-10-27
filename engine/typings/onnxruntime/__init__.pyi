"""The little of ONNX Runtime that Maku uses, typed: the package ships no type information."""

from collections.abc import Mapping, Sequence
from enum import Enum

import numpy as np
import numpy.typing as npt

__version__: str

class ExecutionMode(Enum):
    ORT_SEQUENTIAL = 0
    ORT_PARALLEL = 1

class GraphOptimizationLevel(Enum):
    ORT_DISABLE_ALL = 0
    ORT_ENABLE_BASIC = 1
    ORT_ENABLE_EXTENDED = 2
    ORT_ENABLE_ALL = 99

class SessionOptions:
    enable_mem_pattern: bool
    execution_mode: ExecutionMode
    graph_optimization_level: GraphOptimizationLevel
    def __init__(self) -> None: ...
    def add_free_dimension_override_by_name(self, dim_name: str, dim_value: int) -> None: ...

class NodeArg:
    name: str
    shape: list[int | str | None]

type Provider = str | tuple[str, Mapping[str, object]]

class InferenceSession:
    def __init__(
        self,
        path_or_bytes: str | bytes,
        sess_options: SessionOptions | None = None,
        providers: Sequence[Provider] | None = None,
    ) -> None: ...
    def run(
        self,
        output_names: Sequence[str] | None,
        input_feed: Mapping[str, npt.NDArray[np.float32]],
    ) -> list[npt.NDArray[np.float32]]: ...
    def get_providers(self) -> list[str]: ...
    def get_inputs(self) -> list[NodeArg]: ...

def get_available_providers() -> list[str]: ...
def disable_telemetry_events() -> None: ...
