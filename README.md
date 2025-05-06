# hass-nabucasa

`hass-nabucasa` is the underlying library that enables Home Assistant to connect to and utilize Nabu Casa cloud services.

This library handles a range of cloud-related functionality including:

- Authentication and account management
- Remote UI connections via [SniTun](https://www.github.com/NabuCasa/snitun)
- API interactions with Nabu Casa cloud services
- Voice processing capabilities
- ACME certificate management
- Google Assistant and Alexa integration
- Cloud webhook management
- Cloud file storage and management

## Installation

```bash
python3 -m pip install hass-nabucasa==x.y.z
```

## Release process

`hass-nabucasa` is released through GitHub and published to [PyPI].
The release process is automated and triggered through the GitHub UI:

1. Go to the [GitHub Releases page][releases].
2. Find the draft release created by release-drafter.
3. Verify that the tag and name are the expected ones (e.g., `1.2.3`)
4. Publish the release (and set it as the latest release)

Once published, GitHub Actions workflows automatically:

- Build the package
- Publish to [PyPI]

There is no need to manually update version information in the codebase.

## Development and contributing

### Development environment

We recommend using Visual Studio Code with the official Dev Container extension for development. This provides a consistent, pre-configured environment with all dependencies installed.

This will automatically set up a development environment with all required dependencies.

### Running tests

```bash
scripts/test
```

### Code quality

This project uses pre-commit hooks for code quality checks:

```bash
scripts/lint
```

### Updating voice data

To update the voice data with the latest from Azure:

```bash
python3 -m scripts.update_voice_data
```

You will need to fetch an Azure TTS token. You can generate one by running the [sample key generator server](https://github.com/Azure-Samples/cognitive-services-speech-sdk/tree/master/samples/js/browser/server) and visiting `http://localhost:3001/api/get-speech-token`.

[releases]: https://github.com/NabuCasa/hass-nabucasa/releases
[PyPI]: https://pypi.org/project/hass-nabucasa/
