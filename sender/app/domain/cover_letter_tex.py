"""Сопроводительное письмо в LaTeX. Чистая сборка текста, без запуска tectonic.

Текстовое поле cover letter модель заполняла и раньше. Поле-ЗАГРУЗКА
(«Cover letter», type=file) пропускалось: класть туда CV нельзя, а другого
файла не было — и на обязательном поле заявка парковалась как `manual`, уже
потратив генерацию письма и поднятый браузер. Само письмо при этом написано.

Экранирование здесь не косметика: текст пишет модель по чужой вакансии, и одна
строка вроде «C# & R&D, 50% remote_work» уронила бы сборку целиком, а вместе с
ней и отклик.
"""

# Порядок важен: обратный слэш заменяется первым, иначе он испортит уже
# подставленные команды вроде \&.
_REPLACEMENTS = [
    ("\\", r"\textbackslash{}"),
    ("&", r"\&"),
    ("%", r"\%"),
    ("$", r"\$"),
    ("#", r"\#"),
    ("_", r"\_"),
    ("{", r"\{"),
    ("}", r"\}"),
    ("~", r"\textasciitilde{}"),
    ("^", r"\textasciicircum{}"),
]

# Собирает tectonic, а он работает через XeTeX. Поэтому НЕ T2A с inputenc: это
# подход pdfTeX, и на XeTeX сборка падает с «Font T2A/cmr/m/n not loadable»
# (проверено 2026-08-03). Кириллица здесь берётся из юникодного шрифта, который
# подбирается из того, что есть в системе; если не нашлось ни одного, документ
# соберётся стандартным Latin Modern — латиница выйдет нормально, а русское
# письмо просто не соберётся, и поле останется пустым, как было до этого.
_TEMPLATE = r"""\documentclass[11pt,a4paper]{article}
\usepackage{fontspec}
\IfFontExistsTF{Helvetica}{\setmainfont{Helvetica}}{%
  \IfFontExistsTF{DejaVu Serif}{\setmainfont{DejaVu Serif}}{%
    \IfFontExistsTF{FreeSerif}{\setmainfont{FreeSerif}}{%
      \IfFontExistsTF{Liberation Serif}{\setmainfont{Liberation Serif}}{}}}}
\usepackage[margin=25mm]{geometry}
\usepackage{parskip}
\pagestyle{empty}
\begin{document}
<<<BODY>>>
\end{document}
"""


def escape_tex(text: str) -> str:
    out = str(text or "")
    for raw, safe in _REPLACEMENTS:
        out = out.replace(raw, safe)
    return out


def build_tex(body: str) -> str:
    """Готовый .tex, или «» если письма нет.

    Пустой PDF хуже отсутствующего: в форме он выглядит как приложенное письмо.
    """
    text = str(body or "").strip()
    if not text:
        return ""
    paragraphs = [escape_tex(p.strip()) for p in text.split("\n\n") if p.strip()]
    # Подстановка заменой, а не %-форматированием: в LaTeX «%» это комментарий,
    # и шаблон с \IfFontExistsTF{...}{%} ронял бы формат-строку Python.
    return _TEMPLATE.replace("<<<BODY>>>", "\n\n".join(paragraphs))
