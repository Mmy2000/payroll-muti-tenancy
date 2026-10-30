// The live connection behind the bell: Server-Sent Events, with what a real network needs.
//   - Only the tab in view holds a stream: browsers allow about six connections to a site, and
//     one per open tab would freeze it. A tab coming back reconnects and catches up.
//   - A dropped connection comes back by itself (EventSource does that, from the last event).
//   - When a stream can't be had at all (a server without streaming, a proxy in the way) it
//     falls back on asking every minute, and keeps trying for the stream.
const POLL_EVERY = 60 * 1000;

export function connectLive(url, { onNotification, onUnread, onPoll }) {
  let source = null;
  let timer = null;

  const startPolling = () => {
    timer ??= window.setInterval(() => {
      onPoll();
      open();
    }, POLL_EVERY);
  };
  const stopPolling = () => {
    window.clearInterval(timer);
    timer = null;
  };
  const close = () => {
    source?.close();
    source = null;
  };

  function open() {
    if (source || document.hidden) return;
    source = new EventSource(url);
    source.addEventListener("open", stopPolling);
    source.addEventListener("notification", (event) => onNotification(JSON.parse(event.data)));
    source.addEventListener("unread", (event) => onUnread(JSON.parse(event.data).unread));
    source.addEventListener("error", () => {
      if (source?.readyState !== EventSource.CLOSED) return; // it is reconnecting by itself
      close();
      startPolling();
    });
  }

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      close();
    } else {
      onPoll();
      open();
    }
  });
  window.addEventListener("pagehide", close);
  open();
}
