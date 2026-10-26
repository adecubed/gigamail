// Texts the main process shows by itself: the right-click menu,
// notifications, file dialogs and window titles. The pages keep their own
// dictionary (i18n.js); the main process learns the chosen language from the
// main window through the 'set-lang' message, sent each time it applies one.
const TEXTS = {
  it: {
    menu_cut: 'Taglia', menu_copy: 'Copia', menu_paste: 'Incolla', menu_select_all: 'Seleziona tutto',
    new_mail_one: '{count} nuova mail', new_mail_many: '{count} nuove mail',
    followup_title: 'Follow-up necessario', no_subject: 'Mail senza oggetto',
    update_ready: 'Aggiornamento {version} pronto: si installa alla prossima chiusura.',
    files_documents: 'Documenti', files_all: 'Tutti i file',
    title_reply: 'Nuova risposta', title_new_mail: 'Nuova mail', title_approval: 'Richiesta da approvare',
    title_calendar: 'GigaMail — Calendario', title_marketing: 'GigaMail — Marketing',
    title_ask: 'Chiedi alle mail',
    attachment_exec_blocked: 'è un file che avvia un programma: GigaMail non lo apre. Se ti serve davvero, usa «Salva con nome».',
  },
  en: {
    menu_cut: 'Cut', menu_copy: 'Copy', menu_paste: 'Paste', menu_select_all: 'Select all',
    new_mail_one: '{count} new mail', new_mail_many: '{count} new mails',
    followup_title: 'Follow-up needed', no_subject: 'Mail without a subject',
    update_ready: 'Update {version} ready: it installs the next time you quit.',
    files_documents: 'Documents', files_all: 'All files',
    title_reply: 'New reply', title_new_mail: 'New mail', title_approval: 'Request to approve',
    title_calendar: 'GigaMail — Calendar', title_marketing: 'GigaMail — Marketing',
    title_ask: 'Ask your mail',
    attachment_exec_blocked: 'this file starts a program, so GigaMail does not open it. If you really need it, use "Save as".',
  },
  zh: {
    menu_cut: '剪切', menu_copy: '复制', menu_paste: '粘贴', menu_select_all: '全选',
    new_mail_one: '{count} 封新邮件', new_mail_many: '{count} 封新邮件',
    followup_title: '需要跟进', no_subject: '无主题邮件',
    update_ready: '更新 {version} 已就绪：将在下次退出时安装。',
    files_documents: '文档', files_all: '所有文件',
    title_reply: '新回复', title_new_mail: '新邮件', title_approval: '待批准的请求',
    title_calendar: 'GigaMail — 日历', title_marketing: 'GigaMail — 营销',
    title_ask: '询问邮件',
    attachment_exec_blocked: '该文件会启动程序，GigaMail 不会打开它。如确有需要，请使用“另存为”。',
  },
};

let lang = 'it';

function setLang(value) {
  const l = String(value || '').slice(0, 2).toLowerCase();
  if (TEXTS[l]) lang = l;
  return lang;
}

function getLang() { return lang; }

// mt('update_ready', { version: '0.6.0' }): active language, then English,
// then Italian, then the key itself.
function mt(key, vars) {
  const s = (TEXTS[lang] && TEXTS[lang][key]) || TEXTS.en[key] || TEXTS.it[key] || key;
  if (!vars) return s;
  return s.replace(/\{(\w+)\}/g, (_m, k) => (vars[k] == null ? '' : String(vars[k])));
}

module.exports = { TEXTS, setLang, getLang, mt };
