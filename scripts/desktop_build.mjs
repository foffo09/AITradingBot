// Release build of the Tauri shell without the builder's home directory in the binary (AUDIT-L5).
// shortcut: Cargo `trim-paths` is unstable on Cargo 1.100; switch to it once stable.
import { spawnSync } from "node:child_process";
import { homedir } from "node:os";
import { createRequire } from "node:module";

const remap = `--remap-path-prefix=${homedir()}=~`;
// CARGO_ENCODED_RUSTFLAGS (0x1f-separated) keeps a home path containing spaces intact.
const existing = process.env.CARGO_ENCODED_RUSTFLAGS ?? (process.env.RUSTFLAGS ?? "").split(" ").filter(Boolean).join("\x1f");
const env = { ...process.env, CARGO_ENCODED_RUSTFLAGS: [existing, remap].filter(Boolean).join("\x1f") };
delete env.RUSTFLAGS;
// Run the CLI's JS entry with this Node: no shell, so arguments with spaces survive on Windows too.
const cli = createRequire(import.meta.url).resolve("@tauri-apps/cli/tauri.js");
const result = spawnSync(process.execPath, [cli, "build", ...process.argv.slice(2)], { stdio: "inherit", env });
process.exit(result.status ?? 1);
