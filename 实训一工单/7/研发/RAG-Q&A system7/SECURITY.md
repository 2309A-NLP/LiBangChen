# Security

## PyTorch Model Loading

PyTorch versions before 2.6 are not allowed for loading non-safetensors model
weights because CVE-2025-32434 affects `torch.load`, including
`weights_only=True`.

Use `torch>=2.6` for PyTorch-format weights such as `.bin`, `.pt`, `.pth`, or
`.ckpt`. Safetensors-only model files are not subject to this `torch.load`
version gate.
