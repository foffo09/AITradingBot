// Release build of the Tauri shell without the builder's home directory in the binary (AUDIT-L5).
// shortcut: Cargo `trim-paths` is unstable on Cargo 1.100; switch to it once stable.
import { spawnSync } from "node:child_process";
import { homedir } from "node:os";

const remap = `--remap-path-prefix=${homedir()}=~`;
// CARGO_ENCODED_RUSTFLAGS (0x1f-separated) keeps a home path containing spaces intact.
const existing = process.env.CARGO_ENCODED_RUSTFLAGS ?? (process.env.RUSTFLAGS ?? "").split(" ").filter(Boolean).join("\x1f");
const env = { ...process.env, CARGO_ENCODED_RUSTFLAGS: [existing, remap].filter(Boolean).join("\x1f") };
delete env.RUSTFLAGS;
const result = spawnSync("tauri", ["build", ...process.argv.slice(2)], {
  stdio: "inherit",
  env,
  shell: process.platform === "win32",
});
process.exit(result.status ?? 1);
