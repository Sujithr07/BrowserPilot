import SidebarItem from './SidebarItem'

export default function Sidebar({ history, selectedTaskId, onSelectTask, onNewTask }) {
  return (
    <aside className="flex flex-col h-full w-64 flex-shrink-0 bg-[#161616] border-r border-[#2a2a2a]">
      {/* Header */}
      <div className="flex-shrink-0 flex items-center gap-2 px-4 py-4 border-b border-[#2a2a2a]">
        <div className="w-6 h-6 rounded-md bg-blue-600 flex items-center justify-center flex-shrink-0">
          <svg viewBox="0 0 20 20" fill="currentColor" className="w-3.5 h-3.5 text-white">
            <path d="M3.105 2.289a.75.75 0 00-.826.95l1.903 6.002H10.75a.75.75 0 010 1.5H4.182l-1.903 6.002a.75.75 0 00.826.95 28.896 28.896 0 0015.293-7.154.75.75 0 000-1.115A28.897 28.897 0 003.105 2.289z" />
          </svg>
        </div>
        <span className="text-white text-sm font-semibold tracking-tight">AgentFlow</span>
      </div>

      {/* Task history list */}
      <div className="flex-1 overflow-y-auto py-2 px-2 space-y-0.5">
        {history.length === 0 ? (
          <p className="text-gray-700 text-xs px-2 pt-3">No tasks yet</p>
        ) : (
          history.map((task) => (
            <SidebarItem
              key={task.task_id}
              task={task}
              isSelected={selectedTaskId === task.task_id}
              onClick={() => onSelectTask(task.task_id)}
            />
          ))
        )}
      </div>

      {/* New Task button */}
      <div className="flex-shrink-0 p-3 border-t border-[#2a2a2a]">
        <button
          onClick={onNewTask}
          className="w-full py-2 px-3 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium transition-colors flex items-center justify-center gap-2"
        >
          <svg viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
            <path d="M10.75 4.75a.75.75 0 00-1.5 0v4.5h-4.5a.75.75 0 000 1.5h4.5v4.5a.75.75 0 001.5 0v-4.5h4.5a.75.75 0 000-1.5h-4.5v-4.5z" />
          </svg>
          New Task
        </button>
      </div>
    </aside>
  )
}
