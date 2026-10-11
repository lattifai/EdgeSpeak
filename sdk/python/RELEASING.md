# Python SDK release checklist

The first candidate is `0.1.0a1`. Package publication and deployment of its
CLI, installer, account API and web dependencies are separate operations.
Do not publish any of them without the release owner's explicit approval.

## Package validation

From `sdk/python`, in a disposable virtual environment:

```sh
python -m pip install build twine
python -m build
python -m twine check dist/*.whl dist/*.tar.gz
python -m pip install dist/edgespeak-0.1.0a1-py3-none-any.whl
python -m unittest discover -s tests -v
```

- Check that `pyproject.toml`, `edgespeak.__version__`, and the HTTP User-Agent agree.
- Set `MIN_CLI_VERSION` to the actual minimum required by this SDK release;
  require the matching SDK protocol too. The installer selects latest stable,
  not the floor. Verify compatible CLI reuse without network access and one
  installation attempt for missing/old/incompatible CLI.
- Inspect both distributions: Python modules and `py.typed` in the wheel;
  bilingual READMEs, examples and tests in the source distribution; no local
  credentials, native binaries, models, build output or virtual environments.
- Run the Python SDK workflow on all supported OS/Python combinations. Its
  mock-transport coverage does not replace real runtime acceptance.
- Against a matching CLI, run the opt-in suite with `EDGESPEAK_TEST_CLI`.
  Test owned and attached services, independent clients, shutdown, parent death,
  and account-key expiry/revocation. Verify inference-loaded child cleanup.
- Run real transcription with speakers and semantic sentences, TXT/Caption
  JSON/SRT/ASS alignment, progress, text/paragraph/timed segmentation, diarization,
  batch embeddings and similarity. Validate timestamps in seconds.
- Preserve stable gateway error codes; test quota `reason` and reset time separately
  from expired/revoked keys. Ensure early-closed and incomplete streams release files.

## Coordinated dependency release

Before PyPI upload, after the owner approves the exact versions and surfaces:

1. Confirm the backend migration state in each deployment environment. The
   candidate account-key migration permits null expiry. Do not assume that
   an already-applied migration will run again after editing its source file.
2. Deploy the matching account backend and web UI/docs; check permanent keys,
   one-time secret display, revocation, and shared subscription billing-period
   allowance with real test accounts. Never use production customer data for tests.
3. Publish the matching CLI and official SDK-aware installers. Confirm the
   published CLI passes the SDK version/protocol probe on supported platforms.
4. In a clean user environment, use the candidate wheel with no CLI, then an
   older CLI. Verify latest-stable installation, download integrity checks,
   no account activation prompts during installation, and safe retries.
5. Re-run the package and runtime gates against the exact downloadable bytes.
   Only then publish the reviewed wheel and source distribution to PyPI.

Python is the first supported SDK. Keep the HTTP API language-neutral; add another
language SDK when a concrete integration needs one and its lifecycle/install
behavior can be supported. Do not multiply release artifacts without that need.
