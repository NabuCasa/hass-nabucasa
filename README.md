## Cloud integration in Home Assistant



## Updating voice data

To update the voice data with the latest from Azure, run the following script:

```
python3 -m script.update_voice_data
```

You will need to fetch an Azure TTS token. You can generate one by running the [sample key generator server](https://github.com/Azure-Samples/cognitive-services-speech-sdk/tree/master/samples/js/browser/server) and visiting `http://localhost:3001/api/get-speech-token`.
