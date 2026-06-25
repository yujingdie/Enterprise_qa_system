import ReactMarkdown from 'react-markdown'

interface Props {
  content: string
}

export default function MarkdownRenderer({ content }: Props) {
  return (
    <div className="prose prose-sm max-w-none prose-p:leading-relaxed prose-headings:text-gray-800 prose-code:text-ocean-600 prose-code:bg-ocean-50 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-pre:bg-gray-50 prose-pre:border prose-pre:border-gray-100 prose-blockquote:border-ocean-300 prose-blockquote:text-gray-500 prose-a:text-ocean-600 prose-strong:text-gray-700 prose-ul:pl-5 prose-ol:pl-5 prose-li:my-0.5">
      <ReactMarkdown>{content}</ReactMarkdown>
    </div>
  )
}
