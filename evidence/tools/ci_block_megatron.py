"""Simulate CI: block `megatron` entirely (as on the GitHub CPU runner)."""

import sys


class _Blocked:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "megatron" or fullname.startswith("megatron."):
            raise ModuleNotFoundError(f"No module named {fullname!r} (CI simulation)")
        return None


sys.meta_path.insert(0, _Blocked())
