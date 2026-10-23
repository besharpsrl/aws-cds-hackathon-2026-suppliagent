#!/usr/bin/env node
import { App } from 'aws-cdk-lib';
import { getConfig } from '../config/environments.js';
import { buildApp } from '../lib/app.js';

const app = new App();
buildApp(app, getConfig(app.node.tryGetContext('env'), app.node.tryGetContext('budgetAlertEmail')));
