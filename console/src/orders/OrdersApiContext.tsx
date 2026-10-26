import { createContext, useContext } from 'react';
import { defaultOrdersApi, type OrdersApi } from './api';

/** Lets tests (and later T-46) swap the data source without touching the pages. */
export const OrdersApiContext = createContext<OrdersApi>(defaultOrdersApi);

export const useOrdersApi = (): OrdersApi => useContext(OrdersApiContext);
