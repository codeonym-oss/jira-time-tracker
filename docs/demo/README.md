# The README demo

`docs/demo.gif` is recorded with [VHS](https://github.com/charmbracelet/vhs) from
`demo.tape`, running the released `jtt` from PyPI against the test suite's fake Jira
(`serve.py`, fictional data). From the repository root:

```sh
docker build -t jtt-vhs docs/demo            # --build-arg JTT_VERSION=x.y.z for another release
docker run --rm -v "$PWD":/vhs jtt-vhs docs/demo/demo.tape
```
