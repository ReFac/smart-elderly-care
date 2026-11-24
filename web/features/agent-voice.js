import { node } from './shared.js';
import { capture } from './speech-input.js';

// Leaving the workbench, including a silent permissions refresh, releases the microphone.
function microphoneHost() {
  if (!customElements.get('agent-microphone')) {
    customElements.define(
      'agent-microphone',
      class extends HTMLElement {
        disconnectedCallback() {
          this.release?.();
        }
      },
    );
  }
  return document.createElement('agent-microphone');
}

export function voiceBar(ctx, form, input, send, region, choices) {
  const service = ctx.state.agentCapabilities?.voiceInput;
  const enabled = Boolean(service);
  const unavailable = {
    inactive: '机构语音套餐未开通或已到期，可使用键盘',
    disabled: '机构已暂停语音转写，可使用键盘',
    exhausted: '机构语音额度不足，可使用键盘',
    unconfigured: '语音服务待平台配置，可使用键盘',
  }[service?.state];
  const host = microphoneHost();
  const line = node('div', 'agent-voice-line');
  const heading = node('strong', '', '和协调 Agent 对话');
  const hint = node('span', 'agent-voice-hint');
  hint.id = 'agent-voice-hint';
  hint.setAttribute('role', 'status');
  const err = node('div', 'form-error');
  err.setAttribute('role', 'alert');
  const clock = node('span', 'agent-voice-clock');
  const regionLabel = ctx.agentRegion?.label || ctx.state.uiSettings.institutionName;
  const title = node('div', 'agent-voice-heading', [heading, hint]);
  const label = (button, icon, words) => button.replaceChildren(ctx.ui.icon(icon, 18), words);
  const button = (cls, fn) => {
    const b = node('button', cls);
    b.type = 'button';
    b.addEventListener('click', fn);
    return b;
  };
  const primary = button('agent-voice-main', () => {
    if (phase === 'recording') finish?.();
    else if (phase === 'ready') transcribe();
    else if (phase === 'voice') record();
  });
  const alternate = button('btn btn-secondary', () => {
    if (phase === 'ready') record();
    else if (phase === 'text') reset('voice');
    else reset('text');
  });
  const cancel = button('btn btn-secondary', () => reset(input.value ? 'text' : 'voice'));
  cancel.textContent = '取消录音';
  const file = node('input');
  file.type = 'file';
  file.hidden = true;
  file.accept = '.wav,.ogg,.opus,audio/wav,audio/ogg';
  const pick = button('agent-file-pick', () => file.click());
  pick.textContent = '选择录音文件';
  file.addEventListener('change', () => {
    const blob = file.files[0];
    file.value = '';
    if (!blob) return;
    if (blob.size > 8 * 1024 * 1024 || !blob.size) {
      err.textContent = '请选择 8 MiB 以内的有效录音。';
      return;
    }
    recorded(blob);
  });
  const actions = node('div', 'agent-voice-tools', [alternate, cancel, pick, file]);
  primary.setAttribute('aria-describedby', hint.id);
  input.setAttribute('aria-describedby', hint.id);
  form.setAttribute('aria-label', 'Agent 输入栏');
  line.append(primary, input, send);
  host.append(title, line, clock, actions, err);
  form.append(host);

  let phase = enabled ? 'voice' : 'text';
  let audio = null,
    finish = null,
    generation = 0,
    transcriptId = '';
  const actor = JSON.stringify(ctx.state.user);
  const area = new URLSearchParams(region).toString();
  let message = '';

  function update() {
    const editing = phase === 'text';
    const waiting = phase === 'busy' || phase === 'acquiring';
    form.dataset.phase = phase;
    primary.hidden = editing;
    primary.disabled = waiting || Boolean(unavailable);
    input.hidden = !editing;
    input.required = editing;
    send.hidden = !editing;
    send.disabled = !editing || !input.value.trim() || input.value.length > input.maxLength;
    alternate.hidden = !enabled || ['recording', 'acquiring', 'busy'].includes(phase);
    cancel.hidden = !['recording', 'acquiring', 'ready'].includes(phase);
    pick.hidden = phase !== 'voice' || Boolean(unavailable);
    clock.hidden = phase !== 'recording';
    const text = {
      voice: unavailable ? '语音暂不可用' : '点击开始说话',
      acquiring: '正在打开麦克风',
      recording: '结束录音',
      ready: '确认转写',
      busy: '正在转写…',
    };
    if (!editing) label(primary, phase === 'recording' ? 'pulse' : 'mic', text[phase]);
    if (!alternate.hidden) {
      const keyboard = phase === 'voice';
      label(
        alternate,
        keyboard ? 'keyboard' : 'mic',
        keyboard ? '键盘输入' : phase === 'ready' ? '重新录音' : '语音输入',
      );
    }
    const hints = {
      voice: unavailable || '单段最长 2 分钟',
      acquiring: '请允许浏览器使用麦克风',
      recording: '正在本机录音',
      ready: '已录好 · 可重录或提交 DeepSeek 转写',
      busy: 'DeepSeek 正在处理这段录音',
      text: message || '可输入任务或问题',
    };
    hint.textContent =
      editing && input.value.length > input.maxLength
        ? '文字超出 500 字，请精简后发送（当前 ' + input.value.length + ' 字）'
        : hints[phase];
  }

  function changed() {
    form.dispatchEvent(new Event('input', { bubbles: true }));
  }
  function reset(next) {
    generation++;
    finish?.(false);
    finish = null;
    audio = null;
    err.textContent = '';
    clock.textContent = '';
    phase = next;
    changed();
    update();
    if (phase === 'text') input.focus();
  }
  host.release = () => {
    generation++;
    finish?.(false);
    finish = null;
    audio = null;
  };
  function recorded(blob) {
    finish = null;
    audio = blob;
    phase = blob ? 'ready' : 'voice';
    err.textContent = blob ? '' : '没有录到声音，请重新录音。';
    changed();
    update();
  }
  async function record() {
    reset('acquiring');
    const turn = generation;
    const active = () => host.isConnected && turn === generation;
    try {
      const stop = await capture(
        (blob) => {
          if (active()) recorded(blob);
        },
        (value) => {
          if (active()) clock.textContent = value;
        },
        active,
      );
      if (!active()) {
        stop?.(false);
        return;
      }
      finish = stop;
      phase = 'recording';
      clock.textContent = '0 / 120 秒';
    } catch (error) {
      if (!active()) return;
      phase = 'voice';
      err.textContent =
        error.name === 'NotAllowedError'
          ? '麦克风权限未开启。可在浏览器中授权，或改用键盘及已有录音。'
          : error.message || '无法打开麦克风';
    }
    update();
  }
  async function transcribe() {
    if (phase !== 'ready' || !audio) return;
    phase = 'busy';
    err.textContent = '';
    update();
    const turn = generation;
    try {
      const approved = await ctx.confirmChange({
        title: '发送录音到 DeepSeek',
        target: regionLabel,
        fields: [
          ['语音额度', '按本段音频时长计入机构套餐。'],
          ['用途', '转写文字将回到输入栏，由你核对后发送。'],
        ],
        confirmLabel: '确认转写',
      });
      if (!approved || turn !== generation || !host.isConnected) return;
      const response = await fetch(service.path + (area ? '?' + area : ''), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/octet-stream',
          'X-DeepSeek-Consent': 'yes',
        },
        body: audio,
      });
      const result = await response.json();
      if (!response.ok) {
        if (response.status === 401) await ctx.refreshWorkspace();
        throw new Error(result.error || '转写失败，可重试或改用键盘。');
      }
      if (turn !== generation || !host.isConnected) return;
      const draft = {
        actor,
        area,
        choices: choices.read(),
        transcriptId: result.transcriptId,
        text:
          !input.value.trim() || transcriptId
            ? result.text
            : input.value.trim() + '\n' + result.text,
      };
      // ASR has two audited writes. Refresh all data before allowing a new user-confirmed command.
      if (await ctx.refreshWorkspace(form)) {
        document
          .querySelector('.agent-voicebar')
          ?.dispatchEvent(new CustomEvent('agent-transcribed', { detail: draft }));
      }
    } catch (error) {
      err.textContent = error.message;
    } finally {
      if (turn === generation && host.isConnected) {
        phase = 'ready';
        update();
      }
    }
  }

  function write(text, receipt = '') {
    reset('text');
    input.value = text;
    transcriptId = receipt;
    message = receipt ? '已转写 · 请核对文字后发送' : '';
    changed();
    update();
    input.focus();
  }
  form.addEventListener('agent-transcribed', ({ detail }) => {
    if (!enabled || detail.actor !== actor || detail.area !== area) return;
    choices.restore(detail.choices);
    write(detail.text, detail.transcriptId);
  });
  input.addEventListener('input', update);
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.isComposing && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      if (!send.disabled) form.requestSubmit();
    }
  });
  update();
  return {
    write,
    receipt: () => transcriptId,
    canSend: () => phase === 'text' && !send.disabled,
  };
}
