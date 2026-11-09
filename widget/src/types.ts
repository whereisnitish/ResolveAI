export interface WidgetSettings {
  brand_color: string;
  team_name: string;
  welcome_message: string;
  launcher_position: "right" | "left";
  collect_email: boolean;
}

export interface Visitor {
  name: string;
  email: string;
}

export interface SessionResponse {
  session_token: string;
  expires_in: number;
  visitor_token: string;
  visitor: Visitor;
  settings: WidgetSettings;
}

export interface Attachment {
  id: string;
  filename: string;
  content_type: string;
  size: number;
}

export interface WidgetMessage {
  id: string;
  conversation_id: string;
  body: string;
  author_type: "customer" | "agent" | "ai" | "system";
  author_name: string;
  attachments: Attachment[];
  created_at: string;
}

export interface WidgetConversation {
  id: string;
  number: number;
  status: "open" | "pending" | "resolved" | "closed";
  last_message_preview: string;
  last_message_at: string;
}

export type ServerEvent =
  | { type: "ready" }
  | { type: "message.created"; conversation_id: string; message: WidgetMessage }
  | { type: "typing"; conversation_id: string; actor: "agent" | "customer"; name?: string };

export interface WidgetConfig {
  workspaceId: string;
  apiUrl: string;
}
