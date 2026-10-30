/* Small progressive interactions; no build step or remote scripts. */
document.addEventListener('click', (event) => {
  if (event.target.closest('[data-print]')) window.print();
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

function checkRubricTotals() {
  const imported = document.querySelector('[data-rubric-import]');
  let valid = true;
  document.querySelectorAll('[data-question]').forEach(question => {
    const maximum = Number(question.querySelector('[name$="_max_marks"]').value);
    const fields = [...question.querySelectorAll('[name$="_criterion_marks"]')];
    const total = fields.reduce((sum, input) => sum + Number(input.value), 0);
    const mismatch = maximum > 0 && fields.every(input => input.value !== '') && Math.abs(total - maximum) > 0.000001;
    const warning = question.querySelector('.rubric-total-warning');
    warning.hidden = !mismatch || Boolean(imported?.files.length);
    warning.textContent = `Criteria total ${total} marks, but the question is worth ${maximum}. Adjust the rubric before saving.`;
    if (!warning.hidden) valid = false;
  });
  return valid;
}
document.addEventListener('input', event => {
  if (event.target.closest('[data-question]')) checkRubricTotals();
});
document.querySelector('#assignment-form')?.addEventListener('submit', event => {
  if (!checkRubricTotals()) {
    event.preventDefault();
    document.querySelector('.rubric-total-warning:not([hidden])')?.scrollIntoView({block:'center'});
  }
});
