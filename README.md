# L.A.P.S engine patches (llama.cpp and Strata)

Patches made while running the [L.A.P.S](https://github.com/Razer0028/laps) agent on a home inference server with two old GPUs —
a **Tesla P40 (Pascal, 24 GB)** and an **RTX 2080 SUPER (Turing, 8 GB)** that cannot talk to each other over
PCIe peer-to-peer — and one large MoE model split by layer across both cards.

The patches are published as they were used. They are **not** upstream contributions and are not maintained
against newer upstream versions. Measurements below are from that one machine; every number says when and how it
was measured. Your hardware will give different results.

Some of the kernel code in the Strata patches was written with an AI coding assistant and then measured and checked
on the real machine before use.

日本語の概要は [下](#日本語) にあります。

---

## Strata (`strata/`)

[Strata](https://github.com/Niko1221/Strata) is an MoE inference engine (MIT). Patches are against
**commit `c62d5e3a1` (Strata v0.2.9, engine 0.1.55)** and apply in order with `git apply`:

| Patch | What it does |
|---|---|
| `0001-session-files-layer-split.patch` | Saving and restoring a slot (`/slots/0?action=save|restore`) also works when the model is split across GPUs by layer (`layer_split`). Restore refuses a file made with a different split (HTTP 400) instead of loading wrong state. |
| `0002-tq2-expert-kernels-pascal.patch` | Rewritten CUDA kernels for the TQ2_0 expert matmuls (`gate/up` and `down`) on Pascal: activations staged once in shared memory, wider loads, smaller register use. Outputs are **bit-identical** to the original kernels. Falls back to the original kernel when the shape preconditions are not met. |
| `0003-q8_0-mmvq-pascal.patch` | A faster Q8_0 matrix-vector kernel for 2–4 columns (the speculative-decoding verify width). **Off by default**; enable with `STRATA_Q8_K2=1`. Summation order differs, so it is not bit-identical (max relative difference 1.4e-7 – 1.8e-7 in our tests). |
| `patches-v0.2.16/0001-all-local-changes-v0.2.16.patch` | All three changes ported to Strata v0.2.16 (`64524fb`). Applies cleanly; **not used in production** (see results). |

`tools/strata-session.sh` with `tools/30-session.conf.example` saves the conversation before the server stops and
restores it after it starts (needs patch 0001 and `slot_save_path`). `tools/session_test.py` is the check we used.

### Measured (Strata)

| Change | Before → after | How it was measured |
|---|---|---|
| 0001 + session script: restart with a long conversation | re-reading 44k tokens ≈ 115 s → restore ≈ 1 s | 2026-11-14, P40 + 2080 SUPER, Qwen3.8-Flash-Next Gyro-M TQ2_0 |
| 0002 kernels alone (micro-benchmark, P40) | `gate/up` −25 %, `down` −8 % kernel time (at the 4-token verify width) | 2026-11-18, kernel bench, 300-run median |
| 0003 kernel alone (micro-benchmark, P40) | 1.07× – 1.23× faster, best at 3–4 columns | 2026-11-18, kernel bench, 300-run median |
| 0002 + 0003 in the server (generation) | 51.5 → 55.0 tok/s (+7 %); 53.5 after deployment (+4 %) | 2026-11-18, same 6 prompts, temperature 0, no thinking, 400 tokens, median |
| First measurement of the same | +9.5 % | **over-estimate**, kept here on purpose: re-measuring gave +4 – 7 % |
| v0.2.16 port vs v0.2.9 (prompt processing, 9,665 tokens) | 466 – 484 → 309 – 312 tok/s (**−35 %**) | 2026-11-19, 1 run each. v0.2.16 removed the MMQ prompt kernels, so all layers run on the FP16 path, and the P40's FP16 is 1/64 of its FP32. Generation was within noise. |

Settings that were tried on the same machine and **did not help** (each against the same baseline): overlapping the
two GPUs (`--pipeline-windows 2` with the MTP stage moved: −22 %), the P100 preset (no change), longer drafts
(`--spec 6`: long-context generation 34 → 27 tok/s), raising the 2080 SUPER power limit 200 → 250 W (no change).
What did help without new code: letting expert-cache swaps not block (`STRATA_ADAPT_NOWAIT=1`, `STRATA_ADAPT_LAG=2`,
upstream defaults for P100 and RTX 30 but not for P40): 46.8 → 51.0 tok/s.
Also without new code (2026-11-25): letting the CPU take part of prompt processing (`STRATA_PREFILL_CPU_SHARE=auto`,
`STRATA_PREFILL_CPU_SHARE_MAX=4864`). Reading 100 / 300 / 1,000 / 2,000 new tokens after a cached 18.8k-token prefix took
2.6 / 3.5 / 6.1 / 8.0 s before and 2.0 / 2.5 / 4.8 / 7.2 s after (−10 to −27 %, 5 runs each, median); 2,000 tokens after an
86k-token context 9.0 → 8.0 s. A fresh 28.5k-token read and the generation speed did not change, and a 3-question answer
check stayed correct. Keeping more of the KV cache in VRAM (`--kv-resident 65536` or `131072`) did not help.

---

## llama.cpp (`llama.cpp/`)

Patches against **llama.cpp commit `f9e832c`** (October 2026); they apply in order with `git apply`.
These were used with an earlier llama.cpp-based setup before the switch to Strata.

| Patch | What it does |
|---|---|
| `0001-server-prompt-cache-store.patch` | `llama-server`: keeps evicted prompt-cache entries on disk (`--cache-disk PATH`, `--cache-disk-mib`, `--cache-disk-min-tokens`, `--cache-disk-keep-ckpt`), writes them out on SIGTERM and reads them back after a restart, and can fetch them from another server running the same model (`--cache-peers URL,...` with a shared key file `--cache-peer-key-file`; endpoints `GET /kvstore/index` and `/kvstore/blob/<id>` require the `X-Kvstore-Key` header). Files contain conversation tokens: keep the key file at 0600 and the port on your LAN. Entries with images are not stored. |
| `0002-pipeline-with-overrides.patch` | Allows pipeline parallelism together with tensor overrides (`-ot`) when `LLAMA_PIPELINE_WITH_OVERRIDES` is set. |
| `0003-cuda-staged-copy-without-p2p.patch` | Asynchronous GPU→pinned host→GPU copies between GPUs without P2P, ordered on both streams (`GGML_CUDA_STAGED_COPY=1`). |
| `0004-rpc-fusion-slots-key.patch` | RPC backend: restores op fusion on the server side, caches allocation-size queries, avoids resending unchanged per-token inputs (279 KB → 7 KB per token), adds key-based authentication (`GGML_RPC_KEY_FILE`, `rpc-server -k`; no encryption), an allow list (`GGML_RPC_ALLOW`), timing (`GGML_RPC_PROF`) and pipeline support (`GGML_RPC_NO_PIPELINE=1` to turn off). Old clients and servers still connect. |
| `0005-sched-copies-env.patch` | `GGML_SCHED_COPIES=<n>` lowers the number of pipeline input copies so layer-interleaved splits fit an 8 GB card. |
| `0006-json-schema-optional-any-order.patch` | JSON-schema → grammar: optional properties may appear in any order. Upstream allowed them only in schema order, so a model that wrote one optional argument first could no longer write the others. |

### Measured (llama.cpp)

| Change | Before → after | How it was measured |
|---|---|---|
| 0001 restart with a 40,903-token conversation | 50.3 s → 1.3 s (852 MB read in 0.47 s) | 2026-10-29, P40 + 2080 SUPER, Qwen3.6-35B-A3B fine-tune i1-Q4_K_M with MTP |
| 0001 fetch from another server over 1 Gbps (small model) | 2.8 s (258 MB) vs 4.7 s to recompute 31,939 tokens | 2026-10-29, Qwen3.5-0.8B Q8_0 |
| 0002 + 0003 (prompt / generation) | 975 → 1,008 tok/s (+3 %) / 67.9 → 72.5 tok/s (+6 %) | 2026-10-29, `llama-bench`, pp8192 / tg128, 2 runs each |
| 0004 RPC (generation over 1 Gbps, 80B MoE) | 37.8 → 42.5 tok/s; local overhead −5.9 % → −2 % | 2026-10-29 |
| 0006 (how often the model wrote the search argument) | 2/11 → 8/8 | 2026-10-31, same prompt |

---

## License

MIT — see [`LICENSE`](LICENSE). Both upstream projects are MIT-licensed; their copyright notices are kept in
`LICENSE`.

---

## 日本語

L.A.P.S を自宅の推論機（Tesla P40 と RTX 2080 SUPER の 2 枚・P2P なし・1 つの MoE を層で 2 枚に分けて載せる）で動かしたときの、
Strata と llama.cpp への差分です。使ったときのまま公開しています（上流への寄与ではなく、新しい版への追従もしていません）。

- **Strata（v0.2.9・c62d5e3a1）**: 層を分けた構成でも会話の状態の保存と復元ができるようにする差分と、P40 向けに書き直した計算の核 2 つ
  （TQ2_0 の専門家の掛け算は出力がビット一致・Q8_0 の核は既定で切 `STRATA_Q8_K2=1` で入る）。生成は 51.5 → 53.5〜55.0 tok/s（+4〜7%）。
  最初の測定の +9.5% は上振れでした。v0.2.16 へ移した差分も置きましたが、v0.2.16 は P40 で読み込みが 35% 遅くなるので本番には入れていません。
- **設定だけで効いた物（2026-11-25）**: 読み込みの一部を CPU にも分担させる `STRATA_PREFILL_CPU_SHARE=auto`・`STRATA_PREFILL_CPU_SHARE_MAX=4864`。
  控えに当たる 1.88 万トークンの後に新しく 100／300／1,000／2,000 トークンを読む時間が 2.6／3.5／6.1／8.0 秒 → 2.0／2.5／4.8／7.2 秒
  （−10〜−27%・各 5 回の中央値）。8.6 万トークンの後の 2,000 トークンは 9.0 → 8.0 秒。2.85 万をまとめて読む時と生成の速さは変わらず、
  答えの確かめ 3 問も正しいまま。KV を VRAM に多く置く `--kv-resident 65536`／`131072` は効きませんでした。
- **llama.cpp（f9e832c）**: 控えをディスクに残して起動し直しても続きから読める（4 万トークンで 50 秒 → 1.3 秒）・網の先の GPU（RPC）の改善と鍵・
  道具の任意の引数を順不同で書けるようにする文法の直し、など 6 本。
- 数字はすべてこの 1 台の機械で測った物です。日付・条件・回数を表に書いています。
- 計算の核の一部は AI のコーディング支援で書き、実機で測って確かめてから使いました。
