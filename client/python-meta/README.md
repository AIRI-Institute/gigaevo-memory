# gigaevo-memory (legacy)

This distribution is a **legacy compatibility shim**. The canonical
package is now [`gigaevo-client`](https://pypi.org/project/gigaevo-client/).

Installing `gigaevo-memory` pulls in `gigaevo-client` and registers
the `gigaevo_memory` import path so existing call sites keep working:

```python
from gigaevo_memory import MemoryClient  # still works — emits one DeprecationWarning per process
```

New projects should depend on `gigaevo-client` directly:

```bash
pip install gigaevo-client
```

```python
from gigaevo_client import GigaEvoClient
```

The shim re-exports every public name from `gigaevo_client.*`, mirrors
`__all__` / `__version__`, and registers each submodule in
`sys.modules` so `from gigaevo_memory.<X> import ...` continues to
resolve.

This distribution will be removed in a future release.
