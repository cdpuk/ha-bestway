# Contribution guidelines

Contributing to this project should be as easy and transparent as possible, whether it's:

- Reporting a bug
- Discussing the current state of the code
- Submitting a fix
- Proposing new features

## Github is used for everything

Github is used to host code, to track issues and feature requests, as well as accept pull requests.

Pull requests are the best way to propose changes to the codebase.

1. Fork the repo and create your branch from `master`.
2. Ensure `pre-commit` is set up before making any changes. Run `pre-commit install` to do this.
3. If you've changed something, update the documentation.
4. Test you contribution, and ensure any relevant tests have been updated.
5. Open a pull request.

## Any contributions you make will be under the MIT Software License

In short, when you submit code changes, your submissions are understood to be under the same [MIT License](http://choosealicense.com/licenses/mit/) that covers the project. Feel free to contact the maintainer if that's a concern.

## Report bugs using Github's [issues](../../issues)

GitHub issues are used to track public bugs.
Report a bug by [opening a new issue](../../issues/new/choose).

## Write bug reports with detail, background, and sample code

**Great Bug Reports** tend to have:

- A quick summary and/or background
- Steps to reproduce
  - Be specific!
  - Give sample code if you can.
- What you expected would happen
- What actually happens
- Notes (possibly including why you think this might be happening, or stuff you tried that didn't work)

## Use a Consistent Coding Style

Home Assistant and all custom components use [black](https://github.com/ambv/black) to make sure the code follows the style.

As mentioned above, the `pre-commit` hook will help enforce this.

## Developing & testing

This repository is set up with support for Visual Studio Code development containers. After you've forked and opened the repository, VS Code will prompt you to reopen the project inside a container.

This allows you to easily run the integration against an isolated Home Assistant instance.

## License

By contributing, you agree that your contributions will be licensed under its MIT License.
