/**
 * telegram-jobs — оформление Google Sheet для удобного чтения.
 *
 * Оформляет ТРИ вкладки в едином стиле:
 *   • «Лист1»     — лиды на отправку (основная).
 *   • «Кандидаты» — найденные вакансии (approve/skip).  ← sub-project C
 *   • «Команды»   — очередь /start_search + heartbeat (G1). ← sub-project C
 *
 * Установка:
 *  1) Открой таблицу → Extensions (Расширения) → Apps Script.
 *  2) Удали пустой код, вставь весь этот файл, нажми Save (Ctrl+S).
 *  3) Запусти функцию applyFormatting один раз (выбери её сверху → Run),
 *     дай разрешения при запросе.
 *  4) Дальше в самой таблице появится меню «🧰 Jobs» — оттуда всё под рукой.
 *
 * Скрипт создаёт недостающие вкладки сам и идемпотентен:
 * повторный запуск не трогает данные, только переоформляет.
 */

// ── Конфигурация всех вкладок ───────────────────────────────────────────────
// headers/имена должны совпадать с кодом:
//   main      → app/domain/lead.py (COLUMNS)
//   Кандидаты → app/domain/candidate.py (CANDIDATE_COLUMNS)
//   Команды   → app/infrastructure/control_repo.py (CONTROL_COLUMNS)

var SHEETS = [
  {
    name: 'Лист1',
    headers: ['id', 'Дата добавления', 'Исходный текст', 'Платформа', 'Источник',
              'Вакансия', 'Сообщение', 'Статус', 'Дата отправки', 'Заметка'],
    widths:  [50, 130, 320, 100, 150, 300, 360, 110, 130, 220],
    wrap:    [3, 6, 7, 10],
    center:  [1, 2, 4, 8, 9],
    statusHeader: 'Статус',
    statusColors: {
      'new':     { bg: '#FFF7CC', text: '#7A5C00' },
      'sent':    { bg: '#D9F2D9', text: '#1E5E20' },
      'skipped': { bg: '#ECECEC', text: '#5F6368' },
      'failed':  { bg: '#FAD4D4', text: '#A50E0E' },
      'replied': { bg: '#D6E4FF', text: '#0B3D91' }
    }
  },
  {
    name: 'Кандидаты',
    headers: ['id', 'Платформа', 'Тип', 'URL', 'Title', 'Company',
              'Salary', 'Location', 'Summary', 'Статус', 'Дата'],
    widths:  [50, 100, 80, 280, 240, 160, 110, 130, 300, 100, 120],
    wrap:    [4, 5, 9],              // URL, Title, Summary
    center:  [1, 2, 3, 7, 10, 11],   // id, Платформа, Тип, Salary, Статус, Дата
    statusHeader: 'Статус',
    statusColors: {
      'pending':  { bg: '#FFF7CC', text: '#7A5C00' }, // жёлтый — ждёт ревью
      'taken':    { bg: '#D9F2D9', text: '#1E5E20' }, // зелёный — одобрено
      'rejected': { bg: '#ECECEC', text: '#5F6368' }  // серый — пропущено
    }
  },
  {
    name: 'Команды',
    headers: ['id', 'platform', 'status', 'created_at', 'done_at'],
    widths:  [50, 110, 110, 160, 160],
    wrap:    [],
    center:  [1, 2, 3, 4, 5],
    statusHeader: 'status',
    statusColors: {
      'pending': { bg: '#FFF7CC', text: '#7A5C00' }, // в очереди
      'running': { bg: '#D6E4FF', text: '#0B3D91' }, // выполняется
      'done':    { bg: '#D9F2D9', text: '#1E5E20' }, // готово
      'error':   { bg: '#FAD4D4', text: '#A50E0E' }  // ошибка
    },
    heartbeat: true   // подписать ячейку G1 (пульс воркера)
  }
];

// ── Главная функция ─────────────────────────────────────────────────────────

/** Оформляет все вкладки сразу. */
function applyFormatting() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  SHEETS.forEach(function (cfg) { formatSheet_(ss, cfg); });
  ss.toast('Оформление применено для всех вкладок ✅', 'telegram-jobs', 4);
}

function formatSheet_(ss, cfg) {
  var sh = ss.getSheetByName(cfg.name) || ss.insertSheet(cfg.name);
  ensureHeaders_(sh, cfg);
  styleHeader_(sh, cfg);
  setWidths_(sh, cfg);
  setWrapAndAlign_(sh, cfg);
  freezeAndBanding_(sh, cfg);
  applyStatusRules_(sh, cfg);
  if (cfg.heartbeat) labelHeartbeat_(sh);
}

// ── Шаги оформления (работают с любой вкладкой через cfg) ───────────────────

/** Заголовки в первой строке. */
function ensureHeaders_(sh, cfg) {
  sh.getRange(1, 1, 1, cfg.headers.length).setValues([cfg.headers]);
}

/** Тёмная шапка с белым жирным текстом. */
function styleHeader_(sh, cfg) {
  sh.getRange(1, 1, 1, cfg.headers.length)
    .setBackground('#1F2A44')
    .setFontColor('#FFFFFF')
    .setFontWeight('bold')
    .setFontSize(11)
    .setVerticalAlignment('middle')
    .setHorizontalAlignment('center');
  sh.setRowHeight(1, 38);
}

/** Ширина колонок. */
function setWidths_(sh, cfg) {
  for (var i = 0; i < cfg.widths.length; i++) {
    sh.setColumnWidth(i + 1, cfg.widths[i]);
  }
}

/** Перенос длинных колонок + выравнивание тела. */
function setWrapAndAlign_(sh, cfg) {
  var lastRow = Math.max(sh.getMaxRows(), 2);
  var rows = lastRow - 1;
  sh.getRange(2, 1, rows, cfg.headers.length)
    .setVerticalAlignment('top')
    .setFontSize(10);
  cfg.wrap.forEach(function (col) {
    sh.getRange(2, col, rows, 1).setWrap(true);
  });
  cfg.center.forEach(function (col) {
    sh.getRange(2, col, rows, 1).setHorizontalAlignment('center');
  });
}

/** Закрепить шапку + чередование строк. */
function freezeAndBanding_(sh, cfg) {
  sh.setFrozenRows(1);
  sh.getBandings().forEach(function (b) { b.remove(); });
  var lastRow = Math.max(sh.getLastRow(), 2);
  sh.getRange(1, 1, lastRow, cfg.headers.length)
    .applyRowBanding(SpreadsheetApp.BandingTheme.LIGHT_GREY, true, false);
}

/** Цвета по значению колонки статуса. */
function applyStatusRules_(sh, cfg) {
  if (!cfg.statusColors) { sh.setConditionalFormatRules([]); return; }
  var statusCol = cfg.headers.indexOf(cfg.statusHeader) + 1;
  var statusRange = sh.getRange(2, statusCol, sh.getMaxRows() - 1, 1);
  var rules = [];
  Object.keys(cfg.statusColors).forEach(function (key) {
    var c = cfg.statusColors[key];
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

/** Подпись пульса воркера: F1 = ярлык, G1 пишет сам воркер. */
function labelHeartbeat_(sh) {
  sh.getRange('F1')
    .setValue('heartbeat →')
    .setFontWeight('bold')
    .setFontColor('#5F6368')
    .setHorizontalAlignment('right');
  sh.getRange('G1').setNote('Воркер пишет сюда время последнего «пульса». Пусто = ноут не запускался.');
  sh.setColumnWidth(6, 110);
  sh.setColumnWidth(7, 160);
}

// ── Меню и быстрые действия ─────────────────────────────────────────────────

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('🧰 Jobs')
    .addItem('✨ Применить оформление (все вкладки)', 'applyFormatting')
    .addSeparator()
    .addItem('🔵 Отметить выбранную строку: replied', 'markReplied')
    .addToUi();
}

/** Ставит статус 'replied' в строке текущей выделенной ячейки (вкладка «Лист1»). */
function markReplied() {
  var sh = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Лист1');
  if (!sh) return;
  var row = sh.getActiveCell().getRow();
  if (row < 2) return;
  var statusCol = SHEETS[0].headers.indexOf('Статус') + 1;
  sh.getRange(row, statusCol).setValue('replied');
}
