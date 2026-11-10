# twidr

[![PyPI](https://img.shields.io/pypi/v/twidr)](https://pypi.org/project/twidr/)

🐦️ *the **T**witter–**W**ayback Machine **I**mage **D**ownload **R**obot* 🤖

twidr downloads images from the [Wayback Machine](https://web.archive.org/)'s snapshots of a Twitter (X) account.

To be as kind as possible to Internet Archive's infrastructure, twidr rate-limits itself and creates an on-disk cache of the indices it gets from the Wayback Machine's APIs.

> The Internet Archive plays a crucial role in preserving worldwide knowledge and combatting censorship. **[Donate!](https://archive.org/donate)**

## installing

[pipx](https://pipx.pypa.io/) is the preferred way to install twidr. Unlike [pip](https://pip.pypa.io/) alone: it automatically isolates the package from your other Python packages and puts the package in your [`PATH`](https://en.wikipedia.org/wiki/PATH_(variable)).

```shell
pipx install twidr
```

twidr supports [argcomplete](https://kislyuk.github.io/argcomplete/) shell completions, which you can install for [just twidr](https://kislyuk.github.io/argcomplete/#codecell2) or [all your Python packages](https://kislyuk.github.io/argcomplete/#global-completion).

<details>
<summary>do you <em>really</em> want to use pip?</summary>

pip is not recommended. On pip systems, for global installation:

```shell
pip install twidr
```
</details>

## usage

Alongside its cached indices of Wayback Machine query results, twidr saves its progress as it downloads files. This lets you start a long-running download, pause it, and come back to it.

### examples

Download all the images archived from user @openSUSE into a new directory called `opensuse`:

```bash
twidr opensuse
```

Download images into the current directory:

```bash
twidr opensuse --output .
twidr opensuse -o .
```

See all of twidr's options with `twidr --help`.

## developing and building

This project uses [uv](https://docs.astral.sh/uv/).

Clone the repository with [Git](https://git-scm.com/) and use uv to install dependencies:

```bash
git clone git@github.com:solanto/twidr.git
cd twidr
uv sync
```

Run the program in development with `uv run`:

```bash
uv run twidr
```

And build the package with `uv build`:

```bash
uv build
```

## contributing

Feel free to ask questions or make suggestions here or at [person@dandelion.computer](mailto:person@dandelion.computer). I'll do my best to collaborate with those who'd like to!

If you fork twidr, be sure to change [`lib.meta:ORG_DOMAIN`](src/twidr/lib/meta.py#L10) to your own domain (which could even be something like `your-username.github.io`). twidr uses this identifier to tell Internet Archive's servers exactly whose code is requesting information.

## license

[GNU General Public License v3.0 or later](https://spdx.org/licenses/GPL-3.0-or-later.html). See license in [`LICENSE.md`](LICENSE.md).
