# IMPLEMENT.md

## Retrieved Methodologies (step: moriah-careframe-transplant-packet)

| pattern_id | name | fitness | source | status |
|---|---|---|---|---|
| `f3e564c3-a10c-4fc8-a2ce-ec945eed6f99` | Creation mode: new | 0.9091 (9 green / 0 red) | CAM corpus / unavailable source path | viable |
| `34cb9a68-3cce-48fd-b1c4-986c23bded63` | Creation mode: new | 0.9583 (22 green / 0 red) | CAM corpus / unavailable source path | viable |

### One-line provenance citations

- `f3e564c3-a10c-4fc8-a2ce-ec945eed6f99` - Creation mode: new - fitness 0.9091 (9 green / 0 red) - source: CAM corpus / unavailable source path
- `34cb9a68-3cce-48fd-b1c4-986c23bded63` - Creation mode: new - fitness 0.9583 (22 green / 0 red) - source: CAM corpus / unavailable source path

### Application plan

- APPLY `f3e564c3-a10c-4fc8-a2ce-ec945eed6f99`: structure the MoriahCareFrame work as a new standalone output packet with CLI help, README, runnable smoke path, tests, and no runtime dependency on the source repos.
- APPLY `34cb9a68-3cce-48fd-b1c4-986c23bded63`: preserve the standalone CLI/test/documentation pattern and explicit argparse help path in the generated fused app.
- REJECT `cbe25ded-3ead-4d75-b1c8-13939f31a14f`: stale permission-lattice result; useful as a reminder to preserve read-only source boundaries, but too generic for the packet design.
- REJECT `21a33670-268e-4e92-96a4-067680214d5b`: duplicate stale permission-lattice result.
- REJECT `6e01fcd4-4a72-41e0-baa0-bac233d91f96`: stale creation-mode result with weaker fitness than the applied pattern.
- REJECT `c05ecc45-74dd-4641-b7b2-d43773ad70a7`: creation-mode result for a different domain; useful only as background.
