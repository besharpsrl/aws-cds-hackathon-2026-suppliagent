import { createContext, useContext } from 'react';
import { defaultConversationsApi, type ConversationsApi } from './api';

/** Lets tests swap the data source without touching the pages. */
export const ConversationsApiContext = createContext<ConversationsApi>(defaultConversationsApi);

export const useConversationsApi = (): ConversationsApi => useContext(ConversationsApiContext);
