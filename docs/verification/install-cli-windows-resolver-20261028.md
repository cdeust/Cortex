# Windows local npm CLI resolution

PR814 base: `f67a6cd1640fa3b55665d22d96fac4dd0b9352fe`.
The actual [Windows install job122540076771](https://github.com/cdeust/Cortex/actions/runs/40602876275/job/122540076771)
failed before invoking Claude: the installation check tried to read
`node_modules/.bin/node_modules/@anthropic-ai/claude-code/package.json`.

`shutil.which` selected the local npm `.cmd` shim. The resolver treated its
parent as a global npm prefix. npm's
[documented executable locations](https://docs.npmjs.com/cli/v11/configuring-npm/folders#executables)
place local shims in `node_modules/.bin` and Windows global shims directly in
the prefix. The [cmd-shim source](https://github.com/npm/cmd-shim/blob/v8.0.0/lib/index.js#L56-L79)
constructs targets relative to the selected shim directory.

The resolver now recognizes that local directory pair, including case variants,
then reads the package's declared bin. Other layouts retain global-prefix
resolution. Existing package-containment checks, direct native entrypoints,
legacy JS/Node handling and isolated environment construction are unchanged.
No private CI installation path is hardcoded.

The new filesystem fixtures reproduced five `FileNotFoundError` cases before
the change. Afterward, the focused installation suite passed 19 tests and
10 subtests. It covers local/global native and JS layouts, a global prefix named
`.bin`, case variants, paths containing spaces, package containment, symlink
resolution and existing environment isolation. Ruff, source/craftsmanship gates
and `check_craftsmanship.py --base origin/main` passed.

These fixtures run on the local test host. Native Windows acceptance requires
a successful hosted Windows install job on the updated PR head. No model calls
or installation probes were run for this patch.
