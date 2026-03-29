import React from "react";

/**
 * Lightweight markdown renderer for chat messages.
 * Handles: **bold**, *italic*, numbered lists, and paragraph breaks.
 */

function renderInline(text: string): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  // Match **bold** and *italic* patterns
  const regex = /(\*\*(.+?)\*\*|\*(.+?)\*)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = regex.exec(text)) !== null) {
    // Text before this match
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }

    if (match[2]) {
      // **bold**
      parts.push(<strong key={match.index} className="font-semibold">{match[2]}</strong>);
    } else if (match[3]) {
      // *italic*
      parts.push(<em key={match.index}>{match[3]}</em>);
    }

    lastIndex = match.index + match[0].length;
  }

  // Remaining text after last match
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return parts.length > 0 ? parts : [text];
}

export function renderMarkdown(text: string): React.ReactNode {
  // Split into paragraphs by double newlines
  const paragraphs = text.split(/\n{2,}/);

  return paragraphs.map((paragraph, pIdx) => {
    const trimmed = paragraph.trim();
    if (!trimmed) return null;

    // Check if this paragraph is a numbered list block
    const lines = trimmed.split("\n");
    const isNumberedList = lines.every(
      (line) => /^\d+\.\s/.test(line.trim()) || line.trim() === ""
    );

    if (isNumberedList) {
      return (
        <ol key={pIdx} className="list-decimal list-inside space-y-1.5">
          {lines
            .filter((line) => line.trim())
            .map((line, lIdx) => {
              const content = line.replace(/^\d+\.\s*/, "");
              return <li key={lIdx}>{renderInline(content)}</li>;
            })}
        </ol>
      );
    }

    // Check if it's a bullet list
    const isBulletList = lines.every(
      (line) => /^[-•]\s/.test(line.trim()) || line.trim() === ""
    );

    if (isBulletList) {
      return (
        <ul key={pIdx} className="list-disc list-inside space-y-1">
          {lines
            .filter((line) => line.trim())
            .map((line, lIdx) => {
              const content = line.replace(/^[-•]\s*/, "");
              return <li key={lIdx}>{renderInline(content)}</li>;
            })}
        </ul>
      );
    }

    // Regular paragraph — preserve single newlines as <br>
    return (
      <p key={pIdx}>
        {lines.map((line, lIdx) => (
          <React.Fragment key={lIdx}>
            {lIdx > 0 && <br />}
            {renderInline(line)}
          </React.Fragment>
        ))}
      </p>
    );
  });
}
