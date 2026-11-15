"""Wall-clock supervision for bounded, CPU-only science jobs."""

import multiprocessing

from .contracts import Problem


def _child(writer, name, args, options):
    from . import analysis

    try:
        operation = {"compare": analysis.compare, "detect": analysis.detect, "track": analysis.track}[name]
        writer.send((True, operation(*args, **options)))
    except analysis.AnalysisError as exc:
        writer.send((False, (exc.code, exc.message)))
    finally:
        writer.close()


def run_science(name, time_limit, *args, **options):
    # Use spawn so the child inherits no server sockets, request state or SQLite connections.
    ctx = multiprocessing.get_context("spawn")
    reader, writer = ctx.Pipe(duplex=False)
    child = ctx.Process(target=_child, args=(writer, name, args, options), daemon=True)
    try:
        child.start()
        writer.close()
        if not reader.poll(time_limit):
            raise Problem("LIMIT_REACHED", "The analysis exceeded its processing time budget.", 503, True)
        try:
            ok, payload = reader.recv()
        except EOFError as exc:
            raise Problem("PROCESSING_FAILED", "The analysis worker could not finish.", 503, True) from exc
        if not ok:
            raise Problem(*payload, 409)
        return payload
    finally:
        reader.close()
        writer.close()
        if child.pid is not None:
            child.join(timeout=0.15)
            if child.is_alive():
                child.terminate()
                child.join(timeout=0.5)
            if child.is_alive():
                child.kill()
                child.join()
            child.close()
