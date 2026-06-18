# Demo recording

A one-shot terminal recording proves the clone→demo path. Produce it with
[asciinema](https://asciinema.org):

```bash
# 1. record the command-line proof (stack bring-up + smoke test)
asciinema rec docs/demo.cast --title "VCL reference implementation" --command "bash scripts/record-demo.sh"

# 2. (optional) upload / embed
asciinema upload docs/demo.cast
```

`scripts/record-demo.sh` runs the scripted flow below; the browser walkthrough
(query → trace viewer → PDF export) is in [demo-script.md](demo-script.md) and is best
captured as a short screen capture of <http://localhost:8501>.

> The `.cast` / video asset itself is not committed (binary); regenerate it with the
> command above. CI (`/.github/workflows/ci.yml`) runs the same `scripts/smoke.py` on
> every push, so the demo path is continuously verified.
