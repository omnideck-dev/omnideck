const text = document.querySelector('#text');
const status = document.querySelector('#status');
const metrics = document.querySelector('#metrics');
const buttons = [...document.querySelectorAll('button')];

function setBusy(busy, message) {
  buttons.forEach((button) => { button.disabled = busy; });
  status.textContent = message;
  status.dataset.state = busy ? 'busy' : 'ready';
}

function showError(error) {
  setBusy(false, error.message || 'Action failed');
  status.dataset.state = 'error';
}

document.querySelector('#analyze').addEventListener('click', async () => {
  setBusy(true, 'Running Python action…');
  try {
    const result = await window.omnideck.invoke('analyze', { text: text.value });
    const entries = [
      ['Words', result.words],
      ['Characters', result.characters],
      ['No spaces', result.characters_without_spaces],
      ['Sentences', result.sentences],
      ['Read time', `${result.reading_seconds}s`],
    ];
    metrics.replaceChildren(...entries.map(([label, value]) => {
      const card = document.createElement('div');
      const number = document.createElement('strong');
      const caption = document.createElement('span');
      number.textContent = value;
      caption.textContent = label;
      card.append(number, caption);
      return card;
    }));
    metrics.hidden = false;
    setBusy(false, 'Analysis complete');
  } catch (error) {
    showError(error);
  }
});

document.querySelector('#ask-agent').addEventListener('click', () => {
  window.omnideck.chat.compose({
    text: 'Help me improve this text while preserving its intent:',
    context: { text: text.value },
  });
});

document.querySelectorAll('[data-mode]').forEach((button) => {
  button.addEventListener('click', async () => {
    setBusy(true, `Applying ${button.textContent.toLowerCase()}…`);
    try {
      const result = await window.omnideck.invoke('transform', {
        text: text.value,
        mode: button.dataset.mode,
      });
      text.value = result.text;
      metrics.hidden = true;
      setBusy(false, 'Text updated');
    } catch (error) {
      showError(error);
    }
  });
});
