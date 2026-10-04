def format_note(content, existing, *, author, timestamps, append, now):
    """Apply canonical metadata while preserving the original creation time."""

    def split_header(text):
        header, separator, body = text.partition("\n\n")
        lines = header.splitlines()
        if (
            separator
            and lines
            and all(line.startswith(("Author: ", "Created: ", "Updated: ")) for line in lines)
        ):
            return dict(line.split(": ", 1) for line in lines), body
        return {}, text

    previous, previous_body = split_header(existing)
    _, body = split_header(content)
    metadata = []
    if author:
        metadata.append(f"Author: {author}")
    if timestamps:
        metadata.extend([f"Created: {previous.get('Created', now)}", f"Updated: {now}"])
    if append:
        entry = f"\n\nEntry: {now}\n{content}" if timestamps else content
        body = previous_body + entry
    result = ("\n".join(metadata) + "\n\n" if metadata else "") + body
    if len(result) > 65536:
        raise ValueError("note exceeds 65536 characters")
    return result
