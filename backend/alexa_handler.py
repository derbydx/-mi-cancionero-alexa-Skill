import logging
import uuid

from queue_manager import queue_manager
from config import settings
from history_manager import mark_as_played

logger = logging.getLogger(__name__)


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
        current_song = queue_manager.current()
        logger.info(f"PlaybackNearlyFinished token={token} vid={current_song['video_id'] if current_song else 'None'}")
        song = queue_manager.peek_next()
        if song is None:
            logger.warning("PlaybackNearlyFinished: queue is empty, stopping")
            return {"version": "1.0", "response": {}}
        new_token = str(uuid.uuid4())
        url = f"{settings.proxy_base_url}/proxy/audio/{song['video_id']}"
        logger.info(f"PlaybackNearlyFinished: pre-buffering {song['video_id']} ({song['title']}) "
                     f"new_token={new_token} expected_previous={token}")
        return {
            "version": "1.0",
            "response": {
                "directives": [{
                    "type": "AudioPlayer.Play",
                    "playBehavior": "ENQUEUE",
                    "audioItem": {
                        "stream": {
                            "url": url,
                            "token": new_token,
                            "expectedPreviousToken": token,
                            "offsetInMilliseconds": 0,
                        }
                    },
                }]
            },
        }

    elif request_type == "AudioPlayer.PlaybackStopped":
        current_song = queue_manager.current()
        logger.info(f"PlaybackStopped token={token} offset={offset} "
                     f"vid={current_song['video_id'] if current_song else 'None'}")
        queue_manager.save_offset(offset)
        return {"version": "1.0", "response": {}}

    elif request_type == "AudioPlayer.PlaybackStarted":
        current_song = queue_manager.current()
        queue_manager.set_playback_token(token)
        if current_song:
            mark_as_played(current_song["video_id"])
        logger.info(f"PlaybackStarted token={token} "
                     f"vid={current_song['video_id'] if current_song else 'None'} "
                     f"index={queue_manager.get_index()} loop={queue_manager.is_looping()}")
        return {"version": "1.0", "response": {}}

    elif request_type == "AudioPlayer.PlaybackFinished":
        current_song = queue_manager.current()
        logger.info(f"PlaybackFinished token={token} "
                     f"vid={current_song['video_id'] if current_song else 'None'}")
        song = queue_manager.next()
        if song is None:
            logger.warning("PlaybackFinished: queue is empty")
            return {"version": "1.0", "response": {}}
        url = f"{settings.proxy_base_url}/proxy/audio/{song['video_id']}"
        logger.info(f"PlaybackFinished: advancing to {song['video_id']} ({song['title']})")
        return build_play_directive(url, str(uuid.uuid4()), 0)

    elif request_type == "AudioPlayer.PlaybackFailed":
        current_song = queue_manager.current()
        error = request.get("error", {})
        logger.error(f"PlaybackFailed token={token} vid={current_song['video_id'] if current_song else 'None'} "
                      f"error={error}")
        song = queue_manager.skip()
        if song is None:
            return {"version": "1.0", "response": {}}
        url = f"{settings.proxy_base_url}/proxy/audio/{song['video_id']}"
        logger.info(f"PlaybackFailed: skipping to {song['video_id']} ({song['title']})")
        return build_play_directive(url, str(uuid.uuid4()), 0)

    logger.warning(f"Unknown AudioPlayer event: {request_type}")
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
