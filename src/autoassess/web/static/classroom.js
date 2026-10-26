/* Small progressive interactions; no build step or remote scripts. */
document.addEventListener('click', (event) => {
  const add = event.target.closest('[data-add-question]');
  if (add) {
    const count = document.querySelector('#question-count');
    const index = Number(count.value) + 1;
    if (index > 50) return;
    const wrapper = document.createElement('div');
    wrapper.innerHTML = document.querySelector('#question-template').innerHTML.replaceAll('__INDEX__', String(index));
    const question = wrapper.firstElementChild;
    document.querySelector('#questions').append(question);
    count.value = String(index);
    htmx.process(question);
    question.querySelector('textarea').focus();
  }
  const criterion = event.target.closest('[data-add-criterion]');
  if (criterion) {
    const list = criterion.closest('fieldset').querySelector('.criteria-list');
    const copy = list.firstElementChild.cloneNode(true);
    copy.querySelectorAll('input,textarea').forEach(input => input.value = '');
    list.append(copy);
    copy.querySelector('textarea').focus();
  }
  const remove = event.target.closest('[data-remove-criterion]');
  if (remove && remove.closest('.criteria-list').children.length > 1) remove.closest('.criterion-fields').remove();
});
document.addEventListener('change', event => {
  if (event.target.matches('[data-rubric-import]')) {
    const imported = event.target.files.length > 0;
    document.querySelectorAll('#questions input,#questions textarea').forEach(input => input.required = !imported);
  }
});
document.addEventListener('keydown', event => {
  if (event.ctrlKey || event.metaKey || event.altKey || event.target.closest('input,textarea,select,[contenteditable=true]')) return;
  const key = event.key.toLowerCase();
  const link = document.querySelector(key === 'j' ? '[data-next]' : key === 'k' ? '[data-previous]' : '[data-never]');
  if (link) { event.preventDefault(); window.location.assign(link.href); }
  if (key === 'a') { const form = document.querySelector('[data-accept-form]'); if (form) { event.preventDefault(); form.requestSubmit(); } }
});
document.querySelectorAll('[data-drop-zone]').forEach(zone => {
  zone.addEventListener('dragover', event => { event.preventDefault(); zone.classList.add('dragging'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('dragging'));
  zone.addEventListener('drop', event => {
    event.preventDefault(); zone.classList.remove('dragging');
    const input = zone.querySelector('input[type=file]');
    if (!input.disabled) { input.files = event.dataTransfer.files; input.dispatchEvent(new Event('change', { bubbles:true })); }
  });
});
