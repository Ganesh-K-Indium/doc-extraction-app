import { useOutletContext } from 'react-router-dom';
import type { Workspace } from './api';

export interface WorkspaceContext { workspace: Workspace; reload: () => void }
/** The workspace the current route sits in (provided by WorkspaceLayout). */
export const useWorkspace = () => useOutletContext<WorkspaceContext>();
