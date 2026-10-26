/* 全局状态：跨模块共享的唯一可变对象 */

export const MAX_LOG_LINES = 400;

export const state = {
  tasks: [],
  status: null,
  runs: [],
  logs: [],
  logSeq: 0,
  logFilter: "ALL",
  autoScroll: true,
  editing: null,
  busy: false,
  eventSource: null,
  statusError: false,
  lastStreamErrorAt: 0,
};
