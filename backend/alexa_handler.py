import uuid

from queue_manager import queue_manager
from config import settings


def handle_alexa_request(body: dict) -> dict:
    request = body.get("request", {})
    request_type = request.get("type", "")
    intent = request.get("intent", {})

    if request_type == "LaunchRequest":
        return build_speech_response("Di el nombre de una cancion o artista para comenzar.")
    elif request_type == "IntentRequest":
        return _handle_intent(intent)
    elif request_type.startswith("AudioPlayer."):
        return _handle_audio_player(request_type, request)
    else:
        return build_speech_response("No entiendo ese comando.")


def _handle_intent(intent: dict) -> dict:
    name = intent.get("name", "")

    if name == "BuscarMusicaIntent":
        slots = intent.get("slots", {})
        artista = slots.get("artista", {}).get("value", "")
        cancion = slots.get("cancion", {}).get("value", "")
        query = f"{artista} {cancion}".strip()
        if not query:
            return build_speech_response("Por favor, dime que cancion o artista quieres escuchar.")
        try:
            song = queue_manager.start_from_query(query)
            url = f"{settings.proxy_base_url}/proxy/audio/{song['video_id']}"
            token = str(uuid.uuid4())
            return build_play_response(song["title"], song["artist"], url, token, 0)
        except LookupError:
            return build_speech_response(f"No encontre ninguna cancion para {query}.")
        except Exception:
            return build_speech_response("Hubo un error al buscar la musica.")

    elif name == "AMAZON.NextIntent":
        song = queue_manager.skip()
        if song is None:
            return build_speech_response("No hay mas canciones en la cola.")
        url = f"{settings.proxy_base_url}/proxy/audio/{song['video_id']}"
        return build_play_directive(url, str(uuid.uuid4()), 0)

    elif name == "AMAZON.PauseIntent":
        return {"version": "1.0", "response": {"directives": [{"type": "AudioPlayer.Stop"}], "shouldEndSession": True}}

    elif name == "AMAZON.ResumeIntent":
        current = queue_manager.current()
        if current is None:
            return build_speech_response("No hay musica reproduciendose.")
        url = f"{settings.proxy_base_url}/proxy/audio/{current['video_id']}"
        offset = queue_manager.get_offset()
        return build_play_directive(url, str(uuid.uuid4()), offset)

    elif name == "AMAZON.StopIntent":
        return {"version": "1.0", "response": {"directives": [{"type": "AudioPlayer.Stop"}], "shouldEndSession": True}}

    elif name == "AMAZON.LoopOnIntent":
        queue_manager.loop_on()
        return build_speech_response("Repeticion activada.")

    elif name == "AMAZON.LoopOffIntent":
        queue_manager.loop_off()
        return build_speech_response("Repeticion desactivada.")

    elif name == "AMAZON.StartOverIntent":
        current = queue_manager.current()
        if current is None:
            return build_speech_response("No hay musica reproduciendose.")
        url = f"{settings.proxy_base_url}/proxy/audio/{current['video_id']}"
        return build_play_directive(url, str(uuid.uuid4()), 0)

    else:
        return build_speech_response("No entiendo ese comando.")


def _handle_audio_player(request_type: str, request: dict) -> dict:
    token = request.get("token", "")
    offset = request.get("offsetInMilliseconds", 0)

    if request_type == "AudioPlayer.PlaybackNearlyFinished":
        song = queue_manager.next()
        if song is None:
            return {"version": "1.0", "response": {}}
        url = f"{settings.proxy_base_url}/proxy/audio/{song['video_id']}"
        return {
            "version": "1.0",
            "response": {
                "directives": [{
                    "type": "AudioPlayer.Play",
                    "playBehavior": "ENQUEUE",
                    "audioItem": {
                        "stream": {
                            "url": url,
                            "token": str(uuid.uuid4()),
                            "expectedPreviousToken": token,
                            "offsetInMilliseconds": 0,
                        }
                    },
                }]
            },
        }

    elif request_type == "AudioPlayer.PlaybackStopped":
        queue_manager.save_offset(offset)
        return {"version": "1.0", "response": {}}

    elif request_type in (
        "AudioPlayer.PlaybackStarted",
        "AudioPlayer.PlaybackFinished",
    ):
        return {"version": "1.0", "response": {}}

    elif request_type == "AudioPlayer.PlaybackFailed":
        song = queue_manager.skip()
        if song is None:
            return {"version": "1.0", "response": {}}
        url = f"{settings.proxy_base_url}/proxy/audio/{song['video_id']}"
        return build_play_directive(url, str(uuid.uuid4()), 0)

    return {"version": "1.0", "response": {}}


def build_play_directive(url: str, token: str, offset: int = 0) -> dict:
    return {
        "version": "1.0",
        "response": {
            "directives": [{
                "type": "AudioPlayer.Play",
                "playBehavior": "REPLACE_ALL",
                "audioItem": {
                    "stream": {
                        "url": url,
                        "token": token,
                        "expectedPreviousToken": None,
                        "offsetInMilliseconds": offset,
                    }
                },
            }],
            "shouldEndSession": True,
        },
    }


def build_play_response(title: str, artist: str, url: str, token: str, offset: int = 0) -> dict:
    return {
        "version": "1.0",
        "response": {
            "outputSpeech": {
                "type": "PlainText",
                "text": f"Reproduciendo {title} de {artist}.",
            },
            "directives": [{
                "type": "AudioPlayer.Play",
                "playBehavior": "REPLACE_ALL",
                "audioItem": {
                    "stream": {
                        "url": url,
                        "token": token,
                        "expectedPreviousToken": None,
                        "offsetInMilliseconds": offset,
                    }
                },
            }],
            "shouldEndSession": True,
        },
    }


def build_speech_response(text: str) -> dict:
    return {
        "version": "1.0",
        "response": {
            "outputSpeech": {"type": "PlainText", "text": text},
            "shouldEndSession": False,
        },
    }
