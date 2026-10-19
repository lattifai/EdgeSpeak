# Attach to a GPU server through SSH

Run the speech service on a machine you control, then attach the Python SDK
from another machine. Audio files are uploaded to that server; this deployment
does not keep audio on the client machine. It does not require changes to the
SDK's HTTPS policy.

Install the SDK into your chosen Python environment:

```sh
python -m pip install edgespeak
```

Attaching with `base_url` does not install or upgrade the remote CLI.
The client does not need an account API KEY; requests use the authorization
and usage allowance configured on the gateway. An account API KEY in the
client environment is ignored in this mode.

On the GPU server, verify the installed CLI's `serve --help`, its license state,
and that the selected port is free, then run:

```sh
edgespeak-cli serve --host 127.0.0.1 --port 18118 --device cuda:1 --no-model-sleep
```

Use an available CUDA device. Verify the actual worker device through runtime
logs and `nvidia-smi`; launch flags alone are not evidence of physical GPU
selection. Keep the service supervised by your existing process manager when
running unattended. Do not stop or replace another task's existing service.

On the client, keep this SSH connection running in a separate terminal:

```sh
ssh -NT -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -L 127.0.0.1:18118:127.0.0.1:18118 gpu-host
```

Replace `gpu-host` with your SSH host alias. Both listeners bind only to
loopback. SSH authenticates and encrypts transport between the machines.
If the existing gateway requires a bearer token, supply it through your
environment as `EDGESPEAK_GATEWAY_KEY`, never as an account API key.

```python
import os
from edgespeak import EdgeSpeak

with EdgeSpeak(
    base_url="http://127.0.0.1:18118/v1",
    gateway_key=os.environ.get("EDGESPEAK_GATEWAY_KEY"),
    timeout=1800,
) as client:
    aligned = client.align("speech.wav", text="The exact words spoken.")
    turns = client.diarize("speech.wav")
```

Closing this attached client closes its HTTP connections only. It does not stop
the SSH tunnel or remote service. A timeout does not cancel remote inference;
check the service before retrying a long request. Reconnect SSH if the tunnel
exits. Direct connections to remote gateways still require HTTPS.

## Integration boundaries

- SDK results preserve the API `segments`, `words`, `start`, and `end` contract
  in seconds. Convert application-specific formats in the consuming application.
- Alignment and diarization are separate operations. Anonymous labels do not
  identify people; naming requires independent evidence.
- Reference subtitle times are not alignment constraints. Clients that require
  timestamp windows must explicitly extract audio intervals and restore offsets.
  This is not a replacement for dual-reference or speaker-anchored alignment.
- Summary and translation are agent workflows, not speech-service endpoints.
- Test the deployed gateway, not just its version number: capabilities can differ
  between builds. The plain-text example avoids reference-format negotiation.

The remote attachment path was checked with a short synthetic English clip on
Linux CUDA through an SSH tunnel from macOS: alignment, diarization, and returned
word timestamps worked. This is not a long-podcast or cross-GPU acceptance claim.
