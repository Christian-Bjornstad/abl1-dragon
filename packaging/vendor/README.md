# Pip for Python FELLES

`pip-26.2.2-py3-none-any.whl` is the unmodified PyPI wheel from
https://pypi.org/project/pip/26.2.2/.

SHA-256: `fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70`.

`felles.py` verifies the wheel and runs its CLI in the existing interpreter.
It does not install pip into shared Python or require ensurepip, admin rights,
or another Python executable. Application dependencies still use the per-user
package directory. Existing pip modules and interpreter paths are restored.

Pip and its vendored dependency licenses are included inside the wheel and in
`licenses/`. The wheel must accompany source installations.
