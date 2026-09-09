# Spec manifest — frozen governing documents

Per the Evidence-plane discipline (content-address every artifact), this manifest
records the immutable identity of the frozen governing specification. If a file's
hash no longer matches, treat it as a **new version** and record it as a new row;
never edit a frozen version in place.

| Object | File | Version | SHA-256 | Recorded (UTC) |
| --- | --- | --- | --- | --- |
| Master Specification | `docs/Moten_IP_Invention_Control_Plane_Master_Specification_v1_0.pdf` | V1.0 (frozen) | `1ae1b96df418c73bd4461b69e7c43eaa5c20a133eb28b032078cbf49e6e97aa4` | 2026-09-05 |

## Verify

```bash
sha256sum docs/Moten_IP_Invention_Control_Plane_Master_Specification_v1_0.pdf
# expected: 1ae1b96df418c73bd4461b69e7c43eaa5c20a133eb28b032078cbf49e6e97aa4
```

- `legal_effect` of this record: `provenance_only`. A content hash and internal
  timestamp support provenance; they are **not** a USPTO filing date.
- Superseding V1.0 requires adding a new row (e.g., V1.1) with its own hash and a
  change reason. The V1.0 row and file remain.
