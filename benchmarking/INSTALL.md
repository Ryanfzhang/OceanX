# Server setup (Linux, once)

All commands run from the repository root on the Linux server.

```bash
conda create -n oceanx-bench python=3.11 -y
conda activate oceanx-bench
python -m pip install -r benchmarking/requirements.txt
conda install -c conda-forge bubblewrap libseccomp -y     # OceanX sandbox without sudo
command -v bwrap
```

The host must allow user namespaces (see the OceanX installation guide, "Linux system components").

## Models: one file

Copy the template and fill it in. The file is ignored by git; keep it out of data and result folders.

```bash
cp -n benchmark.example.yaml benchmark.yaml && chmod 600 benchmark.yaml
```

```yaml
model: <provider model id>
oceanx_api: openai          # or anthropic
max_tokens: 32768
openai:
  url: "https://<provider>/v1"
  api_key: "<key>"
```

- **Runs:** every OceanX role in benchmark runs uses this model.
- **Lessons and labels:** `server/research_cli.py` uses the same model for lesson mining and model labels.
- **Your everyday settings:** OceanX settings in `~/.oceanmind` are neither read nor changed.

## Checks

```bash
python benchmarking/server/check_setup.py --agent oceanx
ocean doctor && ocean sandbox-self-check
python -m pytest benchmarking/tests -q
```

Accounts:
- **CMEMS downloads:** `copernicusmarine login`, once.
- **ERA5:** the anonymous Google mirror.
- **NOAA products:** anonymous HTTPS.
