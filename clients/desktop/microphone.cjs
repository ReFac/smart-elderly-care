// Grant microphone access to the institution's main workbench after native consent.
function configureMicrophone(session, target, workspaceWindows, ask) {
  const approved = new WeakSet();
  const pending = new WeakMap();

  function workspacePage(raw) {
    try {
      const page = new URL(raw);
      return page.origin === target.origin && page.pathname === target.pathname;
    } catch {
      return false;
    }
  }
  function eligible(contents, permission, details) {
    return permission === 'media' && workspaceWindows.has(contents) && !contents.isDestroyed()
      && details.isMainFrame && workspacePage(contents.getURL()) && workspacePage(details.requestingUrl);
  }

  session.setPermissionCheckHandler((contents, permission, origin, details) =>
    eligible(contents, permission, details) && origin === target.origin
      && details.mediaType === 'audio' && approved.has(contents)
  );
  session.setPermissionRequestHandler((contents, permission, reply, details) => {
    if (!eligible(contents, permission, details)
        || details.mediaTypes?.length !== 1 || details.mediaTypes[0] !== 'audio') {
      return reply(false);
    }
    if (approved.has(contents)) return reply(true);
    const frame = contents.mainFrame;
    let answer = pending.get(frame);
    if (!answer) {
      answer = Promise.resolve().then(() => ask(contents)).catch(() => false)
        .finally(() => pending.delete(frame));
      pending.set(frame, answer);
    }
    answer.then(accepted => {
      const grant = accepted && eligible(contents, permission, details) && contents.mainFrame === frame;
      if (grant) approved.add(contents);
      reply(Boolean(grant));
    });
  });
}

module.exports = { configureMicrophone };
