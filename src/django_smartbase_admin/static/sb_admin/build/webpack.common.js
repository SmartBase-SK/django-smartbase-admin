const path = require('path')
const webpack = require('webpack')
const MiniCssExtractPlugin = require('mini-css-extract-plugin')
const ESLintPlugin = require('eslint-webpack-plugin')

const entries = {
    main: './src/django_smartbase_admin/static/sb_admin/src/js/main.js',
    table: './src/django_smartbase_admin/static/sb_admin/src/js/table.js',
    chart: './src/django_smartbase_admin/static/sb_admin/src/js/chart.js',
    calendar: './src/django_smartbase_admin/static/sb_admin/src/js/calendar.js',
    main_style: './src/django_smartbase_admin/static/sb_admin/src/css/style.css',
    translations: './src/django_smartbase_admin/static/sb_admin/src/js/translations.js',
    confirmation_modal: './src/django_smartbase_admin/static/sb_admin/src/js/confirmation_modal.js',
    tree_widget: './src/django_smartbase_admin/static/sb_admin/src/js/tree_widget.js',
    tree_widget_style: './src/django_smartbase_admin/static/sb_admin/src/css/tree_widget.css',
    calendar_style: './src/django_smartbase_admin/static/sb_admin/src/css/calendar.css',
}

const projectRoot = process.env.PWD || process.cwd()

module.exports = {
    resolve: {
        symlinks: false
    },
    entry: entries,
    output: {
        clean: {
            keep: /sprites/
        },
        filename: '[name].js',
        path: path.resolve(projectRoot, './src/django_smartbase_admin/static/sb_admin/dist')
    },
    module: {
        rules: [
            {
                test: /\.m?js$/,
                exclude: /(node_modules|bower_components)/,
                use: {
                    loader: 'babel-loader',
                    options: {
                        presets: ['@babel/preset-env'],
                        targets: "defaults",
                        plugins: ['@babel/plugin-proposal-optional-chaining']
                    }
                }
            },
            {
                test: /\.css$/,
                use: [
                    MiniCssExtractPlugin.loader,
                    {
                        loader: 'css-loader',
                        options: {
                            sourceMap: true,
                        },
                    },
                    {
                        loader: "postcss-loader",
                        options: {
                            postcssOptions: {
                                config: path.resolve(projectRoot, './src/django_smartbase_admin/static/sb_admin/build/postcss.config.js'),
                            }
                        },
                    },
                ],
            },
        ]
    },
    plugins: [
        new ESLintPlugin({
            files: ['./src/django_smartbase_admin/static/sb_admin/src/**/*.js'],
        }),
        new MiniCssExtractPlugin({
            filename: '[name].css',
        }),
        new webpack.DefinePlugin({
            'process.env.BUILD': JSON.stringify('web'),
        }),
    ]
}
