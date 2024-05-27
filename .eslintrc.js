module.exports = {
    root: true,
    env: {
        browser: true,
        es2021: true,
        jquery: true,
    },
    extends: [
        'eslint:recommended',
    ],
    parserOptions: {
        ecmaVersion: 'latest',
        sourceType: 'module',
    },
    rules: {
        indent: ['error', 4, { "SwitchCase": 1 }],
        semi: ['error', 'never'],
    },
}
