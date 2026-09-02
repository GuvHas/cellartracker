# Type stubs for `cellartracker`

`cellartracker` 1.1.1 ships no `py.typed` marker, so mypy resolves everything
imported from it to `Any`. That matters more than it looks: `RateLimited`
subclasses `CannotConnect`, and a class whose base is `Any` has `Any` for every
member it did not declare itself - the same hole that made the coordinator's
own `data` untyped before this.

Waving it through with `ignore_missing_imports` would leave that hole open and
make `disallow_any_unimported` unusable, so the four symbols the integration
actually imports are declared here instead. The surface is deliberately narrow:
two constants, two enums and two exception types, pinned by
`cellartracker==1.1.1` in `requirements_test.txt`. If the library grows a
`py.typed` of its own, delete this directory and the `mypy_path` entry.
