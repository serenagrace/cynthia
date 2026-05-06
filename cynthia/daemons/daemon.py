from multiprocessing import Process, Manager, Queue


class Daemon:
    def __init__(self, dman, *args, fbs=None, tqueue=False):
        self.process = None
        self.ns = Manager().Namespace()
        self.ns.run = True
        self.uns = dman.uns
        self.fbs = tuple()
        if fbs is not None:
            for idx in fbs:
                self.fbs += (dman.fb[idx * 2].name,)
                self.fbs += (dman.fb[1 + idx * 2].name,)
        self._args = args

    def start(self, *, daemon=True):
        self.process = Process(
            target=self.loop, args=(self.ns, self.uns) + self.fbs + self._args
        )
        self.process.daemon = daemon
        self.process.start()
