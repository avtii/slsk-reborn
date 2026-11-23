# aioslsk backports

The patches apply to upstream commit `9db3f5d7597e7050f21ff062d92a6708a5572eb1` (1.7.2). They include upstream-style regression tests. The patches to aioslsk are provided under its GPL-3.0-or-later license. The installer builds from that revision and labels the installed distribution `1.7.2+slskreborn.1`. Run it in the Python environment used to run or package slsk-reborn. It requires Git, pip and network access to fetch and build the dependency.

- `transfer-files.patch` confines transfer reads, writes and partial-download cleanup to the configured directories. Symlinks below the selected root are skipped. POSIX uses directory-relative file descriptors. Windows rejects reparse points during the path check, but a concurrent local writer can race that check. The configured root and its ancestors are trusted.
- `message-limits.patch` checks the incoming frame length before reading its body and caps decompressed protocol data. The limits are 16 MiB per encoded message and 64 MiB of expanded fields. A very large legitimate listing may be rejected. File contents travel through a separate streaming reader.

Once a published aioslsk release contains both fixes, update the minimum application dependency, switch the CI, release and source-install instructions back to the regular package, and remove these patches.
