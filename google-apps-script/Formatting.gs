/**
 * telegram-jobs — оформление Google Sheet для удобного чтения.
 *
 * Установка:
 *  1) Открой таблицу → Extensions (Расширения) → Apps Script.
 *  2) Удали пустой код, вставь весь этот файл, нажми Save (Ctrl+S).
 *  3) Запусти функцию applyFormatting один раз (выбери её сверху → Run),
 *     дай разрешения при запросе.
 *  4) Дальше в самой таблице появится меню «🧰 Jobs» — оттуда всё под рукой.
 */

var SHEET_NAME = 'Лист1';

var HEADERS = [
  'id',
  'Дата добавления',
  'Исходный текст',
  'Платформа',
  'Цель',
  'Вакансия',
  'Сообщение',
  'Статус',
  'Дата отправки',
  'Заметка'
];

// Ширина колонок (px), по индексу HEADERS.
var WIDTHS = [50, 130, 320, 100, 150, 300, 360, 110, 130, 220];

// Цвета статусов.
var STATUS_COLORS = {
  'new':     { bg: '#FFF7CC', text: '#7A5C00' }, // жёлтый — ждёт отправки
  'sent':    { bg: '#D9F2D9', text: '#1E5E20' }, // зелёный — отправлено
  'skipped': { bg: '#ECECEC', text: '#5F6368' }, // серый — пропущено
  'failed':  { bg: '#FAD4D4', text: '#A50E0E' }, // красный — ошибка
  'replied': { bg: '#D6E4FF', text: '#0B3D91' }  // синий — ответили
};

function getSheet_() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sh = ss.getSheetByName(SHEET_NAME);
  if (!sh) sh = ss.insertSheet(SHEET_NAME);
  return sh;
}

/** Главная функция: применяет всё оформление сразу. */
function applyFormatting() {
  var sh = getSheet_();

  ensureHeaders_(sh);
  styleHeader_(sh);
  setWidths_(sh);
  setWrapAndAlign_(sh);
  freezeAndBanding_(sh);
  applyStatusRules_(sh);

  SpreadsheetApp.getActiveSpreadsheet().toast('Оформление применено ✅', 'telegram-jobs', 4);
}

/** Заголовки в первой строке (если их нет/не совпадают). */
function ensureHeaders_(sh) {
  var range = sh.getRange(1, 1, 1, HEADERS.length);
  range.setValues([HEADERS]);
}

/** Стиль шапки. */
function styleHeader_(sh) {
  var h = sh.getRange(1, 1, 1, HEADERS.length);
  h.setBackground('#1F2A44')
   .setFontColor('#FFFFFF')
   .setFontWeight('bold')
   .setFontSize(11)
   .setVerticalAlignment('middle')
   .setHorizontalAlignment('center');
  sh.setRowHeight(1, 38);
}

/** Ширина колонок. */
function setWidths_(sh) {
  for (var i = 0; i < WIDTHS.length; i++) {
    sh.setColumnWidth(i + 1, WIDTHS[i]);
  }
}

/** Перенос текста в длинных колонках + выравнивание. */
function setWrapAndAlign_(sh) {
  var lastRow = Math.max(sh.getMaxRows(), 2);
  var body = sh.getRange(2, 1, lastRow - 1, HEADERS.length);
  body.setVerticalAlignment('top').setFontSize(10);

  // Перенос текста: Исходный текст(3), Вакансия(6), Сообщение(7), Заметка(10).
  [3, 6, 7, 10].forEach(function (col) {
    sh.getRange(2, col, lastRow - 1, 1).setWrap(true);
  });
  // По центру: id(1), Платформа(4), Статус(8), даты(2,9).
  [1, 2, 4, 8, 9].forEach(function (col) {
    sh.getRange(2, col, lastRow - 1, 1).setHorizontalAlignment('center');
  });
}

/** Закрепить шапку + чередование строк. */
function freezeAndBanding_(sh) {
  sh.setFrozenRows(1);
  // Убрать старые банды, чтобы не дублировать.
  sh.getBandings().forEach(function (b) { b.remove(); });
  var lastRow = Math.max(sh.getLastRow(), 2);
  var range = sh.getRange(1, 1, lastRow, HEADERS.length);
  range.applyRowBanding(SpreadsheetApp.BandingTheme.LIGHT_GREY, true, false);
}

/** Условное форматирование колонки «Статус» по значению. */
function applyStatusRules_(sh) {
  var statusCol = HEADERS.indexOf('Статус') + 1; // 8
  var maxRows = sh.getMaxRows();
  var statusRange = sh.getRange(2, statusCol, maxRows - 1, 1);

  var rules = [];
  Object.keys(STATUS_COLORS).forEach(function (key) {
    var c = STATUS_COLORS[key];
    rules.push(
      SpreadsheetApp.newConditionalFormatRule()
        .whenTextEqualTo(key)
        .setBackground(c.bg)
        .setFontColor(c.text)
        .setBold(true)
        .setRanges([statusRange])
        .build()
    );
  });
  sh.setConditionalFormatRules(rules);
}

/** Меню в таблице. */
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('🧰 Jobs')
    .addItem('✨ Применить оформление', 'applyFormatting')
    .addSeparator()
    .addItem('🔵 Отметить выбранную строку: replied', 'markReplied')
    .addToUi();
}

/** Ставит статус 'replied' в строке текущей выделенной ячейки. */
function markReplied() {
  var sh = getSheet_();
  var row = sh.getActiveCell().getRow();
  if (row < 2) return;
  var statusCol = HEADERS.indexOf('Статус') + 1;
  sh.getRange(row, statusCol).setValue('replied');
}
