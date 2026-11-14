/* 轻量 Markdown 渲染（零依赖、自动转义，与采集端 Python 版语法对齐） */
(function (global) {
  'use strict';

  function escapeHtml(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  var INLINE_BODY = '\\*\\*[\\s\\S]+?\\*\\*|__[\\s\\S]+?__|~~[\\s\\S]+?~~|`[^`]+`|\\*[^*\\n]+?\\*|_[^_\\n]+?_|!\\[[^\\]]*\\]\\([^)]+\\)|\\[[^\\]]+\\]\\([^)]+\\)';
  var INLINE = new RegExp('(' + INLINE_BODY + ')', 'g');
  var INLINE_FULL = new RegExp('^(?:' + INLINE_BODY + ')$');
  var LINK = /^!?\[([^\]]*)\]\(([^)]+)\)$/;
  var FENCE = /^\s*```/;
  var HEADING = /^(#{1,6})\s+(.*)$/;
  var HR = /^\s*(-{3,}|\*{3,}|_{3,})\s*$/;
  var QUOTE = /^\s*>\s?(.*)$/;
  var UL = /^\s*[-*+]\s+(.*)$/;
  var OL = /^\s*\d+[.)]\s+(.*)$/;
  var TASK = /^\[([ xX])\]\s*(.*)$/;
  var TABLE_SEP = /^\s*\|?[\s:|-]+\|[\s:|-]*$/;

  function safeUrl(url) {
    var u = String(url).trim();
    if (/^(https?:\/\/|mailto:|\/|#)/i.test(u)) return escapeHtml(u);
    return null;
  }

  function inline(text) {
    var parts = String(text || '').split(INLINE);
    return parts.map(function (part) {
      if (!part) return '';
      if (!INLINE_FULL.test(part)) return escapeHtml(part);
      var out;
      if (part.indexOf('**') === 0 || part.indexOf('__') === 0) {
        out = '<strong>' + escapeHtml(part.slice(2, -2)) + '</strong>';
      } else if (part.indexOf('~~') === 0) {
        out = '<del>' + escapeHtml(part.slice(2, -2)) + '</del>';
      } else if (part.charAt(0) === '`') {
        out = '<code>' + escapeHtml(part.slice(1, -1)) + '</code>';
      } else if (part.charAt(0) === '*' || part.charAt(0) === '_') {
        out = '<em>' + escapeHtml(part.slice(1, -1)) + '</em>';
      } else if (part.charAt(0) === '!') {
        var im = part.match(LINK);
        out = '<span class="md-muted">' + escapeHtml(im ? (im[1] || '图片') : part) + '</span>';
      } else if (part.charAt(0) === '[') {
        var lm = part.match(LINK);
        if (lm) {
          var url = safeUrl(lm[2]);
          out = url
            ? '<a class="md-link" href="' + url + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(lm[1]) + '</a>'
            : '<span class="md-link">' + escapeHtml(lm[1]) + '</span>';
        } else out = escapeHtml(part);
      } else out = escapeHtml(part);
      return out;
    }).join('');
  }

  function render(source) {
    var lines = String(source || '').replace(/\r\n/g, '\n').split('\n');
    var out = [], i = 0;
    while (i < lines.length) {
      var line = lines[i];
      if (FENCE.test(line)) {
        var lang = line.trim().replace(/^`+/, '').trim();
        i++;
        var code = [];
        while (i < lines.length && !FENCE.test(lines[i])) { code.push(lines[i]); i++; }
        i++;
        out.push('<pre><code' + (lang ? ' class="language-' + escapeHtml(lang) + '"' : '') + '>'
          + escapeHtml(code.join('\n')) + '</code></pre>');
        continue;
      }
      if (HR.test(line)) { out.push('<hr>'); i++; continue; }
      var h = line.match(HEADING);
      if (h) {
        var lv = h[1].length;
        out.push('<h' + lv + '>' + inline(h[2]) + '</h' + lv + '>');
        i++; continue;
      }
      if (/^\s*\|/.test(line) && i + 1 < lines.length && TABLE_SEP.test(lines[i + 1])) {
        var head = line.trim().replace(/^\||\|$/g, '').split('|').map(function (c) { return c.trim(); });
        i += 2;
        var rows = [];
        while (i < lines.length && /^\s*\|/.test(lines[i])) {
          rows.push(lines[i].trim().replace(/^\||\|$/g, '').split('|').map(function (c) { return c.trim(); }));
          i++;
        }
        var table = '<table><thead><tr>' + head.map(function (c) { return '<th>' + inline(c) + '</th>'; }).join('') + '</tr></thead><tbody>';
        rows.forEach(function (row) {
          table += '<tr>' + row.map(function (c) { return '<td>' + inline(c) + '</td>'; }).join('') + '</tr>';
        });
        out.push(table + '</tbody></table>');
        continue;
      }
      if (QUOTE.test(line)) {
        var quote = [];
        while (i < lines.length && QUOTE.test(lines[i])) { quote.push(lines[i].match(QUOTE)[1]); i++; }
        out.push('<blockquote>' + inline(quote.join(' ')) + '</blockquote>');
        continue;
      }
      var ordered = OL.test(line);
      if (UL.test(line) || ordered) {
        var items = [], n = 1;
        while (i < lines.length) {
          var m = ordered ? lines[i].match(OL) : lines[i].match(UL);
          if (!m) break;
          var item = m[1], task = item.match(TASK), html;
          if (task) html = '<li class="md-task">' + (task[1].toLowerCase() === 'x' ? '☑' : '☐') + ' ' + inline(task[2]) + '</li>';
          else html = '<li>' + inline(item) + '</li>';
          items.push(html); n++; i++;
        }
        out.push('<' + (ordered ? 'ol' : 'ul') + '>' + items.join('') + '</' + (ordered ? 'ol' : 'ul') + '>');
        continue;
      }
      if (!line.trim()) { i++; continue; }
      var para = [line.trim()]; i++;
      while (i < lines.length && lines[i].trim()
        && !(HEADING.test(lines[i]) || HR.test(lines[i]) || QUOTE.test(lines[i])
          || UL.test(lines[i]) || OL.test(lines[i]) || FENCE.test(lines[i]))) {
        para.push(lines[i].trim()); i++;
      }
      out.push('<p>' + inline(para.join(' ')) + '</p>');
    }
    return out.join('\n');
  }

  function strip(source) {
    return String(source || '')
      .replace(/```[\s\S]*?```/g, function (m) {
        return m.split('\n').slice(1, -1).join('\n');
      })
      .replace(/!\[([^\]]*)\]\([^)]+\)/g, '$1')
      .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
      .replace(/<[^>]+>/g, '')
      .replace(/^\s{0,3}#{1,6}\s+/gm, '')
      .replace(/^\s{0,3}>\s?/gm, '')
      .replace(/^\s*[-*+]\s+\[[ xX]\]\s*/gm, '')
      .replace(/^\s*[-*+]\s+/gm, '')
      .replace(/^\s*\d+[.)]\s+/gm, '')
      .replace(/^\s*\[[ xX]\]\s*/gm, '')
      .replace(/^\s*\|?[\s:|-]+\|[\s:|-]*$/gm, '')
      .replace(/^\s*(-{3,}|\*{3,}|_{3,})\s*$/gm, '')
      .replace(/[*_~`|]/g, '')
      .replace(/\n{3,}/g, '\n\n').trim();
  }

  global.renderMarkdown = render;
  global.stripMarkdownText = strip;
  global.escapeHtml = escapeHtml;
})(window);
