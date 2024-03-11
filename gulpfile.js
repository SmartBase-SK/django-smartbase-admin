const gulp = require('gulp')
const glob = require('glob')
const svgstore = require('gulp-svgstore')
const svgmin = require('gulp-svgmin')
const merge = require('merge-stream')

gulp.task('svg-sprites', function () {
    return merge(glob.sync('.src/django_smartbase_admin/static/sb_admin/sprites/*').map(function(spritesDir) {
        return gulp.src(spritesDir + '/*.+(svg)')
            .pipe(svgmin())
            .pipe(svgstore({'inlineSvg': true}))
            .pipe(gulp.dest('.src/django_smartbase_admin/static/sb_admin/dist/sprites/'))
    }))
})
