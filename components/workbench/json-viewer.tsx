interface JsonViewerProps {
  label: string;
  value: unknown;
}

export function JsonViewer({ label, value }: JsonViewerProps) {
  return (
    <section className="json-panel" aria-label={label}>
      <div className="panel-title">{label}</div>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </section>
  );
}
