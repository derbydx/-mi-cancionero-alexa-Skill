import logging
import uuid

from queue_manager import queue_manager
from config import settings
from history_manager import mark_as_played



def get_play_url(video_id: str) -> str:
    return f"{settings.proxy_base_url}/proxy/audio/{video_id}"

logger = logging.getLogger(__name__)


async def handle_alexa_request(body: dict) -> dict:
    request = body.get("request", {})
    request_type = request.get("type", "")
    intent = request.get("intent", {})

    if request_type == "LaunchRequest":
        return build_speech_response("Di el nombre de una cancion o artista para comenzar.")
    elif request_type == "IntentRequest":
        return await _handle_intent(intent)
    elif request_type.startswith("AudioPlayer."):
        return await _handle_audio_player(request_type, request)
    elif request_type.startswith("PlaybackController."):
        return await _handle_playback_controller(request_type)
    elif request_type == "System.ExceptionEncountered":
        error = request.get("error", {})
        cause = request.get("cause", {})
        logger.error(f"System.ExceptionEncountered: error={error} cause={cause} token={request.get('token','')}")
        return {}
    else:
        logger.warning(f"Unknown request type: {request_type}")
        return {"version": "1.0", "response": {}}


async def _handle_playback_controller(request_type: str) -> dict:
    if request_type == "PlaybackController.NextCommandIssued":
        song = queue_manager.skip()
        if song is None:
            return {"version": "1.0", "response": {}}
        url = get_play_url(song['video_id'])
        return build_play_directive(url, str(uuid.uuid4()), 0, song.get('thumbnail'), song['title'], song['artist'])
    elif request_type == "PlaybackController.PreviousCommandIssued":
        # Go back to start of current song, or previous song if near start
        current = queue_manager.current()
        if current is None:
            return {"version": "1.0", "response": {}}
        offset = queue_manager.get_offset()
        if offset > 3000:
            # More than 3 seconds in, restart current song
            url = get_play_url(current['video_id'])
            return build_play_directive(url, str(uuid.uuid4()), 0, current.get('thumbnail'), current['title'], current['artist'])
        # Otherwise skip to previous song (not implemented in queue_manager yet)
        return {"version": "1.0", "response": {}}
    elif request_type in ("PlaybackController.PlayCommandIssued", "PlaybackController.PauseCommandIssued"):
        return {"version": "1.0", "response": {}}
    logger.warning(f"Unknown PlaybackController event: {request_type}")
    return {"version": "1.0", "response": {}}


async def _handle_intent(intent: dict) -> dict:
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
            url = get_play_url(song['video_id'])
            token = str(uuid.uuid4())
            return build_play_response(song["title"], song["artist"], url, token, 0,
                                       song.get('thumbnail'), song['title'], song['artist'])
        except LookupError:
            return build_speech_response(f"No encontre ninguna cancion para {query}.")
        except Exception:
            return build_speech_response("Hubo un error al buscar la musica.")

    elif name == "AMAZON.NextIntent":
        song = queue_manager.skip()
        if song is None:
            return build_speech_response("No hay mas canciones en la cola.")
        url = get_play_url(song['video_id'])
        return build_play_directive(url, str(uuid.uuid4()), 0, song.get('thumbnail'), song['title'], song['artist'])

    elif name == "AMAZON.PauseIntent":
        return {"version": "1.0", "response": {"directives": [{"type": "AudioPlayer.Stop"}], "shouldEndSession": True}}

    elif name == "AMAZON.ResumeIntent":
        current = queue_manager.current()
        if current is None:
            return build_speech_response("No hay musica reproduciendose.")
        url = get_play_url(current['video_id'])
        offset = queue_manager.get_offset()
        return build_play_directive(url, str(uuid.uuid4()), offset, current.get('thumbnail'), current['title'], current['artist'])

    elif name == "AMAZON.StopIntent":
        return {"version": "1.0", "response": {"directives": [{"type": "AudioPlayer.Stop"}], "shouldEndSession": True}}

    elif name == "AMAZON.CancelIntent":
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
        url = get_play_url(current['video_id'])
        return build_play_directive(url, str(uuid.uuid4()), 0, current.get('thumbnail'), current['title'], current['artist'])

    elif name == "AMAZON.PreviousIntent":
        current = queue_manager.current()
        if current is None:
            return build_speech_response("No hay musica reproduciendose.")
        offset = queue_manager.get_offset()
        if offset > 3000:
            url = get_play_url(current['video_id'])
            return build_play_directive(url, str(uuid.uuid4()), 0, current.get('thumbnail'), current['title'], current['artist'])
        return build_speech_response("Ya estas al inicio de la cola.")

    elif name == "MostrarColaIntent":
        q = queue_manager.get_queue()
        items = q["queue"]
        current = q["current"]
        if not items:
            return build_speech_response("La cola esta vacia.")
        total = len(items)
        # List next few songs (up to 5)
        upcoming = []
        for i in range(q["current_index"] + 1, min(q["current_index"] + 6, total)):
            s = items[i]
            upcoming.append(f"{s.get('title', '?')} de {s.get('artist', '?')}")
        if not upcoming:
            return build_speech_response("No hay mas canciones en la cola.")
        text = f"Reproduciendo {items[q['current_index']].get('title')} de {items[q['current_index']].get('artist')}. "
        text += f"Siguen {', '.join(upcoming)}."
        return build_speech_response(text)

    elif name == "AMAZON.FallbackIntent":
        return build_speech_response("Di 'busca' seguido del nombre de la cancion o artista que quieras escuchar.")

    else:
        return build_speech_response("No entiendo ese comando.")


async def _handle_audio_player(request_type: str, request: dict) -> dict:
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
        url = get_play_url(song['video_id'])
        logger.info(f"PlaybackNearlyFinished: pre-buffering {song['video_id']} ({song['title']}) "
                     f"new_token={new_token} expected_previous={token}")
        return {
            "version": "1.0",
            "response": {
                "directives": [{
                    "type": "AudioPlayer.Play",
                    "playBehavior": "ENQUEUE",
                    "audioItem": _build_audio_item(url, new_token, 0, token,
                                                   song.get('thumbnail'), song['title'], song['artist']),
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
        next_song = queue_manager.next()
        if next_song:
            logger.info(f"PlaybackFinished: advanced index to {next_song['video_id']} ({next_song['title']})")
        else:
            logger.warning("PlaybackFinished: queue is empty after advancing")
        return {"version": "1.0", "response": {}}

    elif request_type == "AudioPlayer.PlaybackFailed":
        current_song = queue_manager.current()
        error = request.get("error", {})
        logger.error(f"PlaybackFailed token={token} vid={current_song['video_id'] if current_song else 'None'} "
                      f"error={error}")
        song = queue_manager.skip()
        if song is None:
            return {"version": "1.0", "response": {}}
        url = get_play_url(song['video_id'])
        logger.info(f"PlaybackFailed: skipping to {song['video_id']} ({song['title']})")
        return build_play_directive_audio(url, str(uuid.uuid4()), 0,
                                          song.get('thumbnail'), song['title'], song['artist'])

    logger.warning(f"Unknown AudioPlayer event: {request_type}")
    return {"version": "1.0", "response": {}}


def _build_audio_item(url: str, token: str, offset: int, expected_previous: str | None,
                       thumbnail: str | None, title: str | None, artist: str | None) -> dict:
    item = {
        "stream": {
            "url": url,
            "token": token,
            "expectedPreviousToken": expected_previous,
            "offsetInMilliseconds": offset,
        },
    }
    if title:
        metadata = {"title": title}
        if artist:
            metadata["subtitle"] = artist
        if thumbnail:
            sources = [{"url": thumbnail, "size": "LARGE"}]
            metadata["art"] = {"sources": sources, "contentDescription": title}
            metadata["backgroundImage"] = {"sources": sources, "contentDescription": title}
        item["metadata"] = metadata
    return item


def build_play_directive_audio(url: str, token: str, offset: int = 0,
                                thumbnail: str | None = None, title: str | None = None,
                                artist: str | None = None) -> dict:
    return {
        "version": "1.0",
        "response": {
            "directives": [{
                "type": "AudioPlayer.Play",
                "playBehavior": "REPLACE_ALL",
                "audioItem": _build_audio_item(url, token, offset, None, thumbnail, title, artist),
            }],
        },
    }


def build_play_directive(url: str, token: str, offset: int = 0,
                          thumbnail: str | None = None, title: str | None = None,
                          artist: str | None = None) -> dict:
    return {
        "version": "1.0",
        "response": {
            "directives": [{
                "type": "AudioPlayer.Play",
                "playBehavior": "REPLACE_ALL",
                "audioItem": _build_audio_item(url, token, offset, None, thumbnail, title, artist),
            }],
            "shouldEndSession": True,
        },
    }


def build_play_response(title: str, artist: str, url: str, token: str, offset: int = 0,
                         thumbnail: str | None = None, meta_title: str | None = None,
                         meta_artist: str | None = None) -> dict:
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
                "audioItem": _build_audio_item(url, token, offset, None,
                                               thumbnail, meta_title or title, meta_artist or artist),
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
